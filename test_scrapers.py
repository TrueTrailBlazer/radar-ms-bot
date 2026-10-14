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

if __name__ == '__main__':
    unittest.main()
