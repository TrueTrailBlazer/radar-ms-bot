import unittest
from datetime import datetime, timedelta
import main
from bs4 import BeautifulSoup
import json
import os

class TestRadarScrapers(unittest.TestCase):
    def test_edital_muito_antigo(self):
        # Empty or None
        self.assertFalse(main.edital_muito_antigo(''))
        self.assertFalse(main.edital_muito_antigo(None))
        self.assertFalse(main.edital_muito_antigo('Ver no edital'))
        
        # Future deadlines
        hoje = datetime.now()
        futuro = (hoje + timedelta(days=30)).strftime('%d/%m/%Y')
        self.assertFalse(main.edital_muito_antigo(f'Inscrições até {futuro}'))
        
        # Past deadlines (> 3 days ago)
        passado_recente = (hoje - timedelta(days=10)).strftime('%d/%m/%Y')
        self.assertTrue(main.edital_muito_antigo(f'Inscrições até {passado_recente}'))
        
        # Explicit status
        self.assertTrue(main.edital_muito_antigo('Processo Encerrado'))
        self.assertTrue(main.edital_muito_antigo('Cancelado pelo órgão'))
        self.assertTrue(main.edital_muito_antigo('Concurso Suspenso temporariamente'))
        self.assertTrue(main.edital_muito_antigo('Edital Anulado'))

    def test_normalizar_texto_pdf(self):
        # Soft hyphen and PDF broken ligatures
        sample = 'Ci \xadncia da Computa \xado / Metodologia e\nT\xadnicas da Computa \xado120'
        norm = main.normalizar_texto_pdf(sample)
        self.assertIn('computacao', norm)
        self.assertIn('ciencia', norm)
        self.assertIn('tecnicas', norm)
        
        # Broken informacao, avaliacao, SoMware
        sample2 = 'Informa \xado e Avalia \xado de SoMware'
        norm2 = main.normalizar_texto_pdf(sample2)
        self.assertIn('informacao', norm2)
        self.assertIn('avaliacao', norm2)
        self.assertIn('Software', norm2)

    def test_destacar_termo(self):
        base = "Mensagem teste"
        # Standard keyword
        msg, kw = main.destacar_termo(base, "Vaga para Programador Python")
        self.assertEqual(kw, "PROGRAMADOR")
        self.assertIn("🎯 *ALVO ENCONTRADO:* *PROGRAMADOR*", msg)
        self.assertNotIn("**", msg)
        
        # UFMS keyword fallback
        msg2, kw2 = main.destacar_termo(base, "Vaga na FACOM UFMS", padrao=main.PADRAO_TI_UFMS)
        self.assertEqual(kw2, "FACOM")
        self.assertIn("🎯 *ALVO ENCONTRADO:* *FACOM*", msg2)
        self.assertNotIn("**", msg2)
        
        # Non-matching keyword
        msg3, kw3 = main.destacar_termo(base, "Vaga para Auxiliar Administrativo")
        self.assertIsNone(kw3)
        self.assertEqual(msg3, base)

    def test_padrao_local(self):
        self.assertTrue(main.PADRAO_LOCAL.search("Campo Grande - MS"))
        self.assertTrue(main.PADRAO_LOCAL.search("Câmara de Ponta Porã"))
        self.assertTrue(main.PADRAO_LOCAL.search("Prefeitura de Dourados"))
        self.assertTrue(main.PADRAO_LOCAL.search("Três Lagoas"))
        self.assertTrue(main.PADRAO_LOCAL.search("UFMS"))
        self.assertTrue(main.PADRAO_LOCAL.search("IFMS"))
        self.assertFalse(main.PADRAO_LOCAL.search("Prefeitura de Cuiabá - MT"))
        self.assertFalse(main.PADRAO_LOCAL.search("Goiânia - GO"))

    def test_inatividade_diogrande_desativada(self):
        # Must execute without raising exception or sending message
        main.verificar_inatividade_diogrande()

    def test_diogrande_silent_error_handling(self):
        health_file = "health.json"
        with open(health_file, "r", encoding="utf-8") as f:
            before = json.load(f)
        before_falhas = before.get("Diogrande_falhas", 0)
        
        # Register a silent error
        main.registrar_saude("Diogrande", False, msg_erro="HTTP 403 Test", silencioso=True)
        
        with open(health_file, "r", encoding="utf-8") as f:
            after = json.load(f)
        after_falhas = after.get("Diogrande_falhas", 0)
        self.assertEqual(after_falhas, before_falhas)
        
        # Restore health.json
        main.registrar_saude("Diogrande", True, info_adicional=before.get("Diogrande_info", "Operando normalmente."))

    def test_pci_card_parsing(self):
        # Verify card parsing for div.ea with div.ca and div.cd
        html = """
        <div class="ea" data-url="https://pciconcursos.com.br/noticias/vaga-ti-ms">
            <div class="ca">
                <a href="https://pciconcursos.com.br/noticias/vaga-ti-ms">Prefeitura de Campo Grande</a>
            </div>
            <div class="cd">
                2 vagas até R$ 5.000,00 - Analista de TI - Superior
            </div>
            <div class="ce">
                Inscrições até 30/12/2026
            </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = soup.find("div", class_="ea")
        ca = card.find("div", class_="ca")
        cd = card.find("div", class_="cd")
        ce = card.find("div", class_="ce")
        link_tag = ca.find("a")
        orgao = link_tag.get_text().strip()
        detalhes = cd.get_text(separator=" - ").strip()
        prazo = ce.get_text().strip()
        
        self.assertEqual(orgao, "Prefeitura de Campo Grande")
        self.assertIn("Analista de TI", detalhes)
        self.assertTrue(main.PADRAO_TI.search(detalhes))
        self.assertFalse(main.edital_muito_antigo(prazo))

    def test_sad_blazor_detection(self):
        sample_html = "<html><body><script src='_framework/blazor.web.js'></script></body></html>"
        is_blazor = "_framework/blazor" in sample_html or "blazor.web.js" in sample_html
        self.assertTrue(is_blazor)

    def test_novas_palavras_chave_config(self):
        # Requirements P4: Analista de TI, Tecnologia da Informação, Engenharia de Software, Análise e Desenvolvimento de Sistemas
        termos_obrigatorios = [
            "Analista de TI",
            "Tecnologia da Informação",
            "Engenharia de Software",
            "Análise e Desenvolvimento de Sistemas"
        ]
        for termo in termos_obrigatorios:
            self.assertIn(termo, main.KEYWORDS_CONFIG)
            # Insensitive to uppercase, lowercase and accents
            self.assertTrue(main.PADRAO_TI.search(f"Vaga de {termo.lower()}"))
            self.assertTrue(main.PADRAO_TI.search(f"Concurso para {termo.upper()}"))
            # Without accents
            termo_sem_acento = termo.replace('ã', 'a').replace('õ', 'o').replace('á', 'a').replace('é', 'e').replace('í', 'i')
            self.assertTrue(main.PADRAO_TI.search(f"Edital para {termo_sem_acento}"))

    def test_filtro_duplo_google_alerts(self):
        # Negative cases (police/traffic/accidents with isolated words like redes or sistemas)
        negativos = [
            "Polícia fecha boca de fumo que operava redes de tráfico em Campo Grande",
            "Prefeitura de Campo Grande investe em sistemas de esgoto na região norte",
            "Homem invade loja de informática e furta computadores em Dourados",
            "Empresa abre inscrições para curso de formação em redes sociais em Três Lagoas",
            "Acidente envolvendo caminhão paralisa sistemas de trânsito em MS"
        ]
        for n in negativos:
            m_ti = main.PADRAO_TI_RIGIDO.search(n)
            m_op = main.PADRAO_OPORTUNIDADE.search(n)
            aprovado = bool(m_ti and m_op)
            self.assertFalse(aprovado, f"Falso positivo não deveria passar: {n}")

        # Positive cases (legitimate IT jobs/contests in MS)
        positivos = [
            "Prefeitura de Campo Grande publica edital de concurso com vaga para Programador",
            "UFMS abre inscrições para processo seletivo na área de Ciência da Computação",
            "Novo concurso público em MS oferece salário de até R$ 8 mil para Analista de TI",
            "Processo seletivo simplificado com vagas para Tecnologia da Informação",
            "Governo de MS anuncia contratação de Desenvolvedor com salário atrativo"
        ]
        for p in positivos:
            m_ti = main.PADRAO_TI_RIGIDO.search(p)
            m_op = main.PADRAO_OPORTUNIDADE.search(p)
            aprovado = bool(m_ti and m_op)
            self.assertTrue(aprovado, f"Oportunidade legítima de TI deveria passar: {p}")

    def test_fapec_card_e_vagas_parsing(self):
        html_card = """
        <div class="row">
            <div class="col-md-9">
                <h5>PSV - Processo Seletivo Vestibular - 2027</h5>
                <p>PROCESSO SELETIVO VESTIBULAR UEMS – 2027</p>
                <a href="https://portal.concurso.fundacaofapec.org.br/edital/ver/21">Inscrições Abertas</a>
            </div>
            <div class="col-md-3">
                <p>Período de Inscrição: De 02/09/2026 até 05/11/2026</p>
            </div>
        </div>
        """
        soup_card = BeautifulSoup(html_card, "html.parser")
        link = soup_card.find("a", href=True)
        self.assertEqual(link["href"], "https://portal.concurso.fundacaofapec.org.br/edital/ver/21")

        html_detalhes = """
        <h4>VER EDITAL PSV - Processo Seletivo Vestibular 2027</h4>
        <div>Inscrições de 02/09/2026 - 09:00 até 05/11/2026 - 23:59 Campo Grande - MS</div>
        <div id="vagas">
            <p>1802 - SISTEMAS DE INFORMAÇÃO - BACHARELADO (PONTA PORÃ) - Noturno (30 vagas)</p>
        </div>
        """
        soup_det = BeautifulSoup(html_detalhes, "html.parser")
        titulo = soup_det.find("h4").get_text().replace("VER EDITAL", "").strip()
        vagas = soup_det.find(id="vagas").get_text()
        self.assertEqual(titulo, "PSV - Processo Seletivo Vestibular 2027")
        self.assertTrue(main.PADRAO_TI.search(vagas))

    def test_semadi_acordeon_parsing(self):
        html_acordeon = """
        <div class="acordeon wp-block-nwe-article-toggle">
            <div class="top">
                <h5 class="handle-item">Edital 13/2026 – SECRETARIA MUNICIPAL DE ADMINISTRAÇÃO E INOVAÇÃO – FACILITADOR SOCIAL</h5>
            </div>
            <div class="wp-block-post-content">
                <div class="inner-blocks">
                    <p>DESCRIÇÃO: PROCESSO SELETIVO SIMPLIFICADO para seleção de FACILITADOR SOCIAL (Funções: Instrutor de Informática, Instrutor de Violão)</p>
                    <p><a href="https://cdn.campogrande.ms.gov.br/portal/prod/uploads/sites/37/2026/05/Edital-13-2026.pdf">Edital – Clique Aqui!</a></p>
                </div>
            </div>
        </div>
        """
        soup = BeautifulSoup(html_acordeon, "html.parser")
        ac = soup.find("div", class_="acordeon")
        h = ac.find(class_="handle-item")
        titulo = h.get_text().strip()
        desc = ac.find(class_="inner-blocks").get_text()
        links = [a["href"] for a in ac.find_all("a", href=True)]
        
        self.assertIn("Edital 13/2026", titulo)
        self.assertTrue(main.PADRAO_TI.search(desc))
        self.assertEqual(links[0], "https://cdn.campogrande.ms.gov.br/portal/prod/uploads/sites/37/2026/05/Edital-13-2026.pdf")

    def test_quadrix_ms_e_vagas_parsing(self):
        # Non-MS contest
        html_nao_ms = """
        <div class="dados">
            <h2>Conselho Regional de Arquitetura e Urbanismo do Amapá (CAU-AP)</h2>
        </div>
        <div>Inscrições: 01/10/2026 a 30/10/2026 Macapá - AP</div>
        """
        soup_nao_ms = BeautifulSoup(html_nao_ms, "html.parser")
        txt_nao_ms = soup_nao_ms.get_text()
        self.assertFalse(main.PADRAO_LOCAL.search(txt_nao_ms))

        # MS contest with IT table row
        html_ms = """
        <div class="dados">
            <h2>Conselho Regional de Biologia da 01ª Região (CRBio-SP/MT/MS)</h2>
        </div>
        <div>Inscrições: 21/09/2026 a 21/10/2026 Campo Grande - MS</div>
        <table>
            <tr>
                <td>201</td>
                <td>Técnico - Assistente Administrativo - Mato Grosso do Sul</td>
            </tr>
            <tr>
                <td>401</td>
                <td>Analista - Analista de Tecnologia da Informação</td>
            </tr>
        </table>
        """
        soup_ms = BeautifulSoup(html_ms, "html.parser")
        txt_ms = soup_ms.get_text()
        self.assertTrue(main.PADRAO_LOCAL.search(txt_ms))
        
        vagas_ti = [tr.get_text() for tr in soup_ms.find_all("tr") if main.PADRAO_TI.search(tr.get_text())]
        self.assertEqual(len(vagas_ti), 1)
        self.assertIn("Tecnologia da Informação", vagas_ti[0])

    def test_health_registration_novos_scrapers(self):
        # Test registering health for FAPEC, SEMADI_PMCG and Quadrix
        main.registrar_saude("FAPEC", True, info_adicional="Teste FAPEC OK")
        main.registrar_saude("SEMADI_PMCG", True, info_adicional="Teste SEMADI OK")
        main.registrar_saude("Quadrix", True, info_adicional="Teste Quadrix OK")

        with open("health.json", "r", encoding="utf-8") as f:
            h = json.load(f)

        self.assertEqual(h.get("FAPEC_falhas"), 0)
        self.assertEqual(h.get("FAPEC_info"), "Teste FAPEC OK")
        self.assertTrue(h.get("FAPEC_data"))

        self.assertEqual(h.get("SEMADI_PMCG_falhas"), 0)
        self.assertEqual(h.get("SEMADI_PMCG_info"), "Teste SEMADI OK")
        self.assertTrue(h.get("SEMADI_PMCG_data"))

        self.assertEqual(h.get("Quadrix_falhas"), 0)
        self.assertEqual(h.get("Quadrix_info"), "Teste Quadrix OK")
        self.assertTrue(h.get("Quadrix_data"))

if __name__ == '__main__':
    unittest.main()
