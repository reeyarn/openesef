"""
`tax_pres_py.py` is the main Python code file; 
`pyx` is its mirror file for cython compilation. 

"""

from openesef.util.util_mylogger import setup_logger 
from openesef.util.ram_usage import check_memory_usage, safe_numeric_conversion, mem_tops
import logging 
import os
import re
import gc
import pandas as pd
import numpy as np
from openesef.taxonomy.xlink import XLink
from itertools import chain
import traceback
import tracemalloc
from tqdm import tqdm

import warnings

# Specifically ignore only SettingWithCopyWarning
#warnings.simplefilter(action='ignore', category=pd.errors.SettingWithCopyWarning)
# cython: language_level=3
# distutils: language = c++

# Disable pandas warnings
import pandas as pd
#pd.options.mode.chained_assignment = None

if __name__=="__main__":
    log_filename= "/tmp/log_main_20250305_p0.log"
    if os.path.exists(log_filename):
        os.remove(log_filename)
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/", full_format=True, formatter_string='%(name)s.%(levelname)s: %(message)s',pid=0)
else:
    logger = logging.getLogger("openesef.engines.tax_pres") 

"""
Primary-statement detection.

Role NAMES cannot be used to find the primary statements. Across the EU corpus only
~60% of filings name their roles in English; ~21% use the local language ('Bilanz',
'Kapitalflussrechnung', 'KoncernensBalansrkning') and ~19% use bare IFRS role NUMBERS
('ias_1_role-210000'), which no keyword list in any language can ever match. Matching on
the name therefore fails for ~40% of filings -- and it fails SILENTLY, yielding a filing
with no primary statements at all.

So detection is anchored to two things that are language-independent:
  1. the IFRS presentation role NUMBER, which the IFRS taxonomy fixes per statement, and
  2. the ANCHOR CONCEPTS a statement is made of -- a balance sheet contains Assets and
     Liabilities whatever it is called.
"""

# IFRS presentation role numbers (IAS 1 / IAS 7 numbering).
_IFRS_ROLE_CODES = {
    '210000': 'SFP',  # Statement of financial position, current/non-current
    '220000': 'SFP',  # Statement of financial position, order of liquidity
    '310000': 'SOP',  # Statement of profit or loss, by function of expense
    '320000': 'SOP',  # Statement of profit or loss, by nature of expense
    '330000': 'SOP',  # Statement of profit or loss, single statement
    '410000': 'OCI',  # Statement of comprehensive income, OCI net of tax
    '420000': 'OCI',  # Statement of comprehensive income, OCI before tax
    '510000': 'SCF',  # Statement of cash flows, direct method
    '520000': 'SCF',  # Statement of cash flows, indirect method
    '610000': 'SCE',  # Statement of changes in equity
}
# IAS 1.10A lets a filer present profit or loss and OCI EITHER as two statements (a
# separate income statement, 3x0000, followed by an OCI statement, 4x0000) OR as ONE
# combined statement of comprehensive income. In the single-statement case the filer
# numbers that one statement 410000/420000, and it IS the statement of profit or loss --
# there is no other. So a 4x0000 role means "OCI continuation" only when a dedicated P&L
# network also exists; on its own it is the SOP. Treating 4x0000 as categorically not-SOP
# left 116 of the 10,287 EU filings reporting no income statement at all.
_PL_ROLE_CODES = {'310000', '320000', '330000'}
_OCI_ROLE_CODES = {'410000', '420000'}
# 'role-210000', 'ias_1_role-210000', 'esef_role-000000' -> the six digits.
_ROLE_CODE_RE = re.compile(r'role-(\d{6})')

# Concepts that a statement is MADE of. Namespace prefix is stripped before matching, so
# an extension namespace that reuses a standard local name still counts.
_STATEMENT_ANCHORS = {
    'SFP': {'Assets', 'Liabilities', 'EquityAndLiabilities', 'Equity',
            'CurrentAssets', 'NoncurrentAssets', 'CurrentLiabilities', 'NoncurrentLiabilities'},
    'SOP': {'ProfitLoss', 'Revenue', 'RevenueFromContractsWithCustomers', 'GrossProfit',
            'ProfitLossBeforeTax', 'ProfitLossFromOperatingActivities', 'CostOfSales',
            'OperatingExpense'},
    'SCF': {'CashFlowsFromUsedInOperatingActivities', 'CashFlowsFromUsedInInvestingActivities',
            'CashFlowsFromUsedInFinancingActivities', 'CashAndCashEquivalents',
            'IncreaseDecreaseInCashAndCashEquivalents'},
    'OCI': {'OtherComprehensiveIncome', 'ComprehensiveIncome'},
    'SCE': {'IssuedCapital', 'RetainedEarnings', 'SharePremium'},
}
# Two anchors, not one: one anchor is noise (a cover page mentions Equity; a note mentions
# CashAndCashEquivalents). Two cleanly separates real statements from everything else.
_MIN_ANCHORS = 2

_DISCLOSURE_RE = r'disclosure|notes|details|schedule|policies|table'
_KEYWORD_RE = {
    'SOP': r"operation|profit|income|earning",
    'SFP': r"balance.?sheet|financial.?position",
    'SCF': r"cash.?flow|statement.?of.?cash",
}

# ---------------------------------------------------------------------------
# Multilingual fallback, ported verbatim from proj_esef's `_anchoring.py`
# (PRIMARY_ROLE_PATTERNS / ROOT_CONCEPT_ANCHORS). openesef is the library, so it
# should own this list rather than each consumer re-curating it.
#
# Two extra signals, both used only when the IFRS role NUMBER is absent:
#   * the network's ROOT concept. ESEF RTS Article 4 requires every primary
#     statement's presentation network to anchor to one of a small set of IFRS
#     abstracts, and the root's local name identifies the statement type exactly,
#     in any language.
#   * a curated multilingual regex over the role name -- the safety net for
#     filings that are neither IFRS-numbered nor Article-4 anchored.
# ---------------------------------------------------------------------------
_ROOT_CONCEPT_ANCHORS = {
    "StatementOfFinancialPositionAbstract": "SFP",
    "StatementOfFinancialPositionLineItems": "SFP",  # alternative root sometimes used
    "IncomeStatementAbstract": "SOP",
    "StatementOfComprehensiveIncomeAbstract": "SOP",
    "ProfitOrLoss": "SOP",
    "ProfitOrLossAbstract": "SOP",
    "StatementOfCashFlowsAbstract": "SCF",
    "StatementOfChangesInEquityAbstract": "SCE",
}

_PRIMARY_ROLE_PATTERNS = [
    # ============================== SFP ==============================
    # Statement of Financial Position / Balance Sheet
    (
        re.compile(
            r"("
            # --- English (BE/DK/IE/IS/IT/LU/NL/NO/SE/UNK; ESMA / IFRS-conventional) ---
            r"StatementOfFinancialPosition|BalanceSheet|FinancialPosition|"
            r"balance-sheet|"
            # --- German (AT/DE) ---
            r"(?:Konzern)?Bilanz(?!ierung)|"
            # --- French (FR/BE-W) ---
            # 'Bilan' (single 'l') = balance sheet. Etat de la situation financiere.
            r"Bilan(?![cs])|"
            r"Etat(?:s?Consolide(?:e|s)?)?DeLaSituationFinanciere|"
            r"tat(?:s?Consolide?)?DeLaSituationFinanci[èe]re|"
            r"Étatconsolide?delasituationfinanci[eè]re|"
            r"Etats?DeLaSituationFinanciere|"
            r"tatdelasituationfinanci|"
            r"Actif(?!s\b)?XBRL|^Actif$|^Passif$|"
            # --- Italian (IT) ---
            r"StatoPatrimoniale|^SP$|"
            r"Prospettodellasituazionepatrimonialee?finanziaria|"
            r"ProspettoDellaSituazionePatrimoniale|"
            r"SITUAZIONEPATRIMONIALE|"
            # --- Spanish (ES) ---
            r"Estado(?:Consolidado)?DeSituaci(?:o|ó)n(?:Financiera)?|"
            r"Estadodesituacin?financiera|"
            r"ESTADOSDESITUACI(?:O|Ó)NFINANCIERA|"
            r"BalanceConsolidado|"
            # --- Finnish (FI) ---
            r"^Tase$|^Konsernitase$|Taseet?|"
            # --- Portuguese (PT) ---
            r"PosicaoFinanceira|Posiç(?:ã|a)o(?:Consolidada)?Financeira|"
            r"Demonstrac(?:ao|oes)DaPosicao|Demonstraç(?:ão|ões)DaPosição|"
            r"BalançoConsolidado|^BSCons$|^BsAtivoPt|^BsPassivoECapitalProprioPt|"
            r"Demonstraodaposiofinanceira|DemonstraesConsolidadasDaPosio|"
            r"DemonstraesConsolidadasDaPosicao|DemonstracoesConsolidadasDaPosicao|"
            r"POSI(?:Ç|C)(?:Ã|A)OFINANCEIRA|"
            # --- Polish (PL) ---
            r"(?:Skonsolidowane)?SprawozdanieZSytuacjiFinansowej|^Bilans$|"
            # --- Belgian Dutch (BE-V) ---
            r"OverzichtVanDeFinancielePositie|"
            r"Overzichtvandefinancile?positie|"
            # --- Swedish (SE/UNK) ---
            r"RapportO?[Ee]verFinansiellSta?ellning|RapportOEverFinansielStaellning|"
            r"KoncernensBalansrkning|"
            # --- Slovenian (SI) ---
            r"(?:Konsolidiran|Skupinski|Revidiranikonsolidirani)?[Ii]zkazfinan(?:c|č)nega(?:polo(?:z|ž)aja|polo(?:z|ž)aja)|"
            # --- Lithuanian (LT) ---
            r"FinansinesBuklesAtaskaita|FinansinėsBūklėsAtaskaita|"
            r"Konsoliduotair?atskirafinansin|"
            # --- Estonian (EE) ---
            r"FinantsseisundiAruanne|Konsolideeritud[Ff]inantsseisundi|"
            # --- Hungarian (HU) ---
            r"Konszolidáltmérleg|"
            # --- Romanian (RO) ---
            r"^Sofp$|Situatia(?:consolidata)?apozitieifinanc|"
            # --- Greek (GR) ---
            r"ΚΑΤΑΣΤΑΣΗΟΙΚΟΝΟΜΙΚΗΣΘΕΣΗΣ|"
            # --- IFRS standardized role codes ---
            # 210000 (current/non-current), 220000 (liquidity).
            r"role-2[12]0000|role_2[12]0000|ias_1_2[12]0000|ias_1_role-2[12]0000|"
            r"\b2[12]0000\b"
            r")",
            re.IGNORECASE,
        ),
        "SFP",
    ),
    # ============================== SOP ==============================
    # Statement of Profit or Loss / Income / Comprehensive Income
    (
        re.compile(
            r"("
            # --- English ---
            r"StatementOfProfitOrLoss|StatementOfComprehensiveIncome|"
            r"IncomeStatement|ProfitOrLossSection|StatementOfPerformance|"
            r"ComprehensiveIncome|ProfitOrLoss(?!Notes)|"
            r"StatementsOfIncome|StatementOfIncome|"
            r"ConsolidatedStatementsOfIncome|ConsolidatedStatementOfIncome|"
            r"Consolidatedstatements?ofincome|"
            r"ChangeEquity|^ProfitLoss$|^AProfitAndLoss$|"  # NO variants
            r"^WynikFinansowy$|"
            r"comprehensive-income|^income$|"
            r"Statementofincomeloss|"
            # --- Finnish (FI) ---
            r"Tuloslaskelma|Laajatuloslaskelma|"
            # --- German (AT/DE) ---
            r"Gesamtergebnisrechnung|"
            r"Gewinn(?:Und|Oder|UndVerlust|OderVerlust|Verlust)(?:rechnung)?|"
            r"Ergebnisrechnung|"
            # --- French (FR/BE-W) ---
            r"CompteDeResultat|CompteDeRésultat|CompteDeRsultat|"
            r"Etat(?:s?Consolide(?:e|s)?)?DuResultat(?:Global)?|"
            r"tatConsolidDuRsultat|"
            r"tatdursultatglobal|tatdesfluxdursultat|"
            r"Étatconsolidédesrésultats|"
            r"EtatRésultGlob|EtatResultGlob|EtatRsultGlob|"
            r"Etats?Consolides?DuResultat|"
            r"^Resultat$|^Cdr$|^CrConso$|"
            r"^P[lL]$|^Pn[lL]$|^OCI$|^Oci$|^Pl[0-9]+$|^Pnl[0-9]+$|"
            # --- Italian (IT) ---
            r"ContoEconomico|"
            r"Prospettodellutileperdita|"
            r"ProspettoUtilePerdita|UtileOPerdita|"
            r"PROSPETTODELLUTILECOMPLESSIVO|"
            r"PROSPETTODELLUTILEPERDITA|"
            r"^CE$|^PL$|^PN$|"  # Italian abbreviations: ConE, ProfLoss, PatNet
            # --- Spanish (ES) ---
            r"EstadoDe(?:l)?Resultado|EstadoDeResultadoGlobal|"
            r"Estadodel?Resultado|EstadodelresultadoglobalcomponentesORI|"
            r"Estadodelresultadoglobalderesultadospornaturaleza|"
            r"ESTADOSDELRESULTADO|"
            r"^Resultado(?:Resumen)?$|"
            # --- Portuguese (PT) ---
            r"Demonstrac(?:ao|oes)DosResultados|Demonstraç(?:ão|ões)DosResultados|"
            r"ResultadoGlobal|RESULTADOSGLOBAIS|RESULTADOSPORNATUREZA|"
            r"^DrPt$|^PLCons$|^OCICons$|^RendimentoIntegralPt$|"
            r"Demonstraodorendimentointegral|"
            r"DemonstracoesConsolidadasDoOutro|DemonstraesConsolidadasDoOutro|"
            r"OutroRendimentoIntegral|RendimentoIntegral|"
            # --- Polish (PL) ---
            r"Rachunek(?:Wynikow|ZyskowI?Strat)|"
            r"SKONSOLIDOWANE\w*DOCHODOW|"
            r"(?:Skonsolidowane)?SprawozdanieZ(?:Calkowitych|całkowitych)?Dochodow|"
            r"^WynikFinansowy$|"
            # --- Belgian Dutch (BE-V) ---
            r"OverzichtVanHetTotaalresultaat|Overzichtvanhettotaalresultaat|"
            r"^WinstVerlies$|"
            # --- Swedish (SE/UNK) ---
            r"RapportO?[Ee]verTotalresultat|"
            r"KoncernensRapportverTotalresultat|"
            r"InkomstskattAvseendeKomponenterIO?Evrigt|"
            # --- Slovenian (SI) ---
            r"(?:Konsolidiran|Skupinski|Revidiranikonsolidirani|RevidiranIzkaz)?"
            r"[Ii]zkaz(?:drugega)?(?:vse)?obsegajo(?:c|č)egadonosa|"
            r"(?:Konsolidiran|Skupinski|Revidiranikonsolidirani)?[Ii]zkazposlovnegaizida|"
            # --- Lithuanian (LT) ---
            r"BendrujuPajamuAtaskaita|PelnasArbaNuostoliai|"
            r"BendrųjųPajamųAtaskaita|"
            r"Konsoliduotair?atskirakit|Konsoliduotair?atskirapelno|"
            # --- Estonian (EE) ---
            r"KasumijaMuuKoondkasumi|Konsolideeritud[Kk]asumi|"
            r"KOnsolideeritud[Kk]asumi|KoondkasumiAruanne|"
            r"KOnsolideeritud[Kk]asumi-jaMuuKoondkasumi|"
            # --- Hungarian (HU) ---
            r"Konszolidálteredménykimutatás|Konszolidáltátfogóeredménykimutatás|"
            # --- Romanian (RO) ---
            r"^Soci$|ProfitSauPierdere|Situati[ae](?:Consolidata)?[Aa]Rezultatului|"
            r"SituatiaRezultatuluiGlobal|"
            # --- Greek (GR) ---
            r"ΚΑΤΑΣΤΑΣΗΑΠΟΤΕΛΕΣΜΑΤΩΝ|ΚΑΤΑΣΤΑΣΗΛΟΙΠΩΝΣΥΝΟΛΙΚΩΝΕΣΟΔΩΝ|"
            # --- IFRS codes ---
            # 310000 (PL by function), 320000 (PL by nature), 330000 (single statement),
            # 410000, 420000 (OCI components).
            r"role-3[123]0000|role_3[123]0000|ias_1_3[123]0000|ias_1_role-3[123]0000|"
            r"role-4[12]0000|role_4[12]0000|ias_1_4[12]0000|ias_1_role-4[12]0000|"
            r"\b3[123]0000\b|\b4[12]0000\b"
            r")",
            re.IGNORECASE,
        ),
        "SOP",
    ),
    # ============================== SCF ==============================
    # Statement of Cash Flows
    (
        re.compile(
            r"("
            # --- English ---
            r"StatementOfCashFlows?|CashFlowStatement|CashFlow(?!footnotes)|"
            r"cash-flow|"
            # --- Finnish (FI) ---
            r"Rahavirtalaskelma|Konsernirahavirtalaskelma|"
            # --- German (AT/DE) ---
            r"Kapitalflussrechnung|"
            # --- French (FR/BE-W) ---
            r"TableauDesFluxDeTresorerie|TableauDesFluxDeTrsorerie|"
            r"FluxDeTresorerie|"
            r"Étatconsolidédesfluxdetrésorerie|"
            # --- Italian (IT) ---
            r"RendicontoFinanziario|Resocontofinanziario|RENDICONTO|"
            # FR / accent-stripped variants of fluxdetresorerie
            r"tatdesfluxdetrsorerie|etatdesfluxdetresorerie|"
            r"fluxdetrsorerie|fluxdetresorerie|"
            # --- Spanish (ES) ---
            r"EstadoDeFlujosDeEfectivo|"
            r"ESTADOSDEFLUJOSDEEFECTIVO|Estadodeflujosdeefectivomtodoindirecto|"
            r"Estadodeflujosdeefectivo|"
            # --- Portuguese (PT) ---
            r"Demonstrac(?:ao|oes)DosFluxosDeCaixa|"
            r"Demonstraç(?:ão|ões)DosFluxosDeCaixa|FluxosDeCaixa|"
            r"^FluxosCX$|^FluxosCaixaPt$|"
            # --- Polish (PL) ---
            r"Przeplywy(?:Pieniezne)?|Przepływy(?:Pieniężne)?|"
            r"(?:Skonsolidowane)?SprawozdanieZPrzeplywowPienieznych|"
            # --- Belgian Dutch (BE-V) ---
            r"Kasstroomoverzicht|"
            # --- Swedish (SE/UNK) ---
            r"RapportO?[Ee]verKassafl(?:o|ö)eden|"
            r"KassafldesanalysFrKoncernen|Kassafl(?:o|ö)edesanalys|"
            # --- Slovenian (SI) ---
            r"(?:Konsolidiran|Skupinski|Revidiranikonsolidirani)?[Ii]zkazdenarn(?:ihtokov|egatoka)|"
            # --- Lithuanian (LT) ---
            r"PiniguSrautuAtaskaita|PinigųSrautųAtaskaita|"
            r"Konsoliduotair?atskirapinig|"
            # --- Estonian (EE) ---
            r"RahavoogudeAruanne|Konsolideeritud[Rr]ahavoogude|"
            # --- Greek (GR) ---
            r"ΚΑΤΑΣΤΑΣΗΤΑΜΕΙΑΚΩΝΡΟΩΝ|"
            # --- Romanian (RO) abbreviation ---
            r"^Socf$|"
            # --- IFRS codes ---
            # 510000 (direct), 520000 (indirect).
            r"role-5[12]0000|role_5[12]0000|ias_1_5[12]0000|ias_7_5[12]0000|"
            r"ias_(?:1|7)_role-5[12]0000|"
            r"\b5[12]0000\b"
            r")",
            re.IGNORECASE,
        ),
        "SCF",
    ),
    # ============================== SCE ==============================
    # Statement of Changes in Equity
    (
        re.compile(
            r"("
            # --- English ---
            r"StatementOfChangesInEquity|StatementOfEquity|ChangesinEquity|"
            r"ChangeInEquity|equity-changes|"
            r"ConsolidatedStatementsOfChanges|ConsolidatedStatementOfChanges|"
            r"CONSOLIDATEDSTATEMENTS?OFCHANGESIN|"
            # --- Finnish (FI) ---
            r"OmanPaaomanMuutokset|OmanPääomanMuutokset|Pääomalaskelma|"
            r"Laskelma\w*OmanP[a-z]+omanMuutoks|LaskelmaKonserninOmanP[a-z]+omanMuutoks|"
            # --- German (AT/DE) ---
            r"Eigenkapital\w{0,20}rechnung|"
            # --- French (FR/BE-W) ---
            r"VariationsDesCapitauxPropres|EtatDesVariations|"
            r"TableauDeVariatIonDesFondsPropres|TableauDesVariations|"
            r"^CapitauxPropres$|"
            # --- Italian (IT) ---
            r"VariazioniPatrimonio|VariazionidelPatrimonio|"
            r"VariazioniDiPatrimonioNetto|"
            r"Prospetto(?:Delle)?Variazioni|"
            r"PROSPETTODELLEVARIAZIONI|"
            r"VariazioneDelPatrimonioNetto|"
            r"^PNMOV$|"
            # --- Spanish (ES) ---
            r"EstadoDeCambiosEnElPatrimonio|"
            r"EstadoDe?cambiosenelpatrimonio|"
            # --- Portuguese (PT) ---
            r"Demonstrac(?:ao|oes)Das?Alterac|"
            r"Demonstraç(?:ão|ões)Das?Alteraç|"
            r"Demonstraodasalteraesnocapital|"
            r"ALTERACOESNOCAPITAL|ALTERAÇÕESNOCAPITAL|"
            r"^RecEquityCons$|^CapitalPt$|"
            # --- Polish (PL) ---
            r"KapitalyWlasne|Kapitały\w*Własne|Zmiany\w*Kapital(?:e|y)\w*Wlasn|"
            r"SprawozdanieZeZmianWKapitaleWlasnym|"
            r"ZestawienieZmianWSkonsolidowanymKapitaleWlasnym|"
            # --- Belgian Dutch (BE-V) ---
            r"MutatieoverzichtVanHetEigenVermogen|"
            r"Mutatieoverzichtvanheteigenvermogen|"
            # --- Swedish (SE/UNK) ---
            r"RapportO?[Ee]verFo?eraendringarIEgetKapital|"
            r"FoeraendringarIEgetKapital|EgetKapital(?:OchSkulder)?|"
            # --- Slovenian (SI) ---
            r"(?:Konsolidiran|Skupinski|Revidiranikonsolidirani)?[Ii]zkaz"
            r"(?:lastniskegakapitala|gibanjakapitala|sprememblastni(?:s|š)kegakapitala)|"
            # --- Lithuanian (LT) ---
            r"NuosavoKapitaloPokyciuAtaskaita|NuosavoKapitaloPokyčiųAtaskaita|"
            r"Konsoliduotair?atskiranuosav|"
            # --- Estonian (EE) ---
            r"OmakapitaliMuutusteAruanne|Konsolideeritud[Oo]makapitali|"
            # --- Hungarian (HU) ---
            r"Konszolidáltsajáttőkeváltozáskimutatása|"
            # --- Greek (GR) ---
            r"ΚΑΤΑΣΤΑΣΗΜΕΤΑΒΟΛΩΝΙΔΙΩΝΚΕΦΑΛΑΙΩΝ|"
            # --- Romanian (RO) ---
            r"^Soce(?:[0-9]+)?$|Situatia(?:consolidata)?amodificarilorcapital|"
            # --- IFRS code ---
            # 610000.
            r"role-610000|role_610000|ias_1_610000|ias_1_role-610000|\b610000\b"
            r")",
            re.IGNORECASE,
        ),
        "SCE",
    ),
]


## Since 20250301:
class TaxonomyPresentation:
    """
    Main class that processes taxonomy presentation networks and organizes concepts into 
    primary statements and disclosures.
    
    Attributes:
        tax: The taxonomy object being processed
        reporter: TaxonomyReporter instance for label handling
        concept_df: DataFrame containing all concepts
        allowed_segments_by_statement: Dict mapping statements to allowed segments
        concept_dict: Dict containing all concepts
        statement_concepts: Dict mapping statement names to lists of concept details
        disclosure_concepts: Dict mapping disclosure names to lists of concept details
        statement_dimensions: Dict containing allowed dimensions per statement
        so_name: Name of Statement of Operations
        fp_name: Name of Financial Position statement
        cf_name: Name of Cash Flow statement
    
    Methods:
        populate_concept_df(): Creates DataFrame from concept dictionaries
        _is_primary_statement(role_name): Determines if a role represents a primary statement
        _process_network_dimensions(network, statement_name): Processes dimensions in a network
        _validate_segment(segment_data, statement_name): Validates segment data against statement
        _process_taxonomy(): Main method to process taxonomy and build concept dictionaries
        is_valid_concept(concept_qname): Checks if a concept exists in presentation
        get_concept_info(concept_qname): Gets detailed information about a concept
        is_valid_segment(concept_qname, segment_data, statement_name): Validates segment data    
    """
    def __init__(self, tax, reporter=None):
        self.tax = tax
        self.reporter = reporter
        self.concept_df = None
        self.link_df = None
        self.allowed_segments_by_statement = {}
        self.concept_dict = {}  # Main concept dictionary
        self.statement_concepts = {}  # Dict mapping statement names to concept lists
        self.disclosure_concepts = {}  # Dict mapping disclosure names to concept lists
        self.statement_dimensions = {}  # Track allowed dimensions per statement
        self.statement_roles = {}  # statement_name -> full role URI (carries the IFRS role number)
        self.network_concepts = {}  # statement_name -> [concept qname]; drives anchor scoring
        self.network_roots = {}  # statement_name -> {root concept local name}; ESEF Art.4 anchor
        self._process_taxonomy() # THE MAIN FUNCTION
        self.statement_types = {}
        self.name_sop = self._pick_primary_statement("SOP")
        self.name_sfp = self._pick_primary_statement("SFP")
        self.name_scf = self._pick_primary_statement("SCF")
        if not all([self.name_sop, self.name_sfp, self.name_scf]):
            logger.warning(f"Not all primary statements found: SOP={self.name_sop}, SFP={self.name_sfp}, SCF={self.name_scf}")

        #SOP: Statement of Operations, SFP: Statement of Financial Position, CFS: Statement of Cash Flows
        self.statement_types = {
            name: type_code
            for name, type_code in {
                self.name_sop: "SOP",
                self.name_sfp: "SFP",
                self.name_scf: "CFS"
            }.items()
            if name is not None
        }
        self._promote_picked_statements()

        self.populate_concept_df()  # Populate the DataFrame upon initialization
        logger.info(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        if self.concept_df is not None and not self.concept_df.empty:
            logger.info(self.concept_df.statement_name.value_counts())
        else:
            logger.warning("concept_df is empty/None — 0 presentation networks found for this filing")

        
        # # Debug output to check what's in the concept dictionary
        # logger.info(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        # if len(self.concept_dict) == 0:
        #     logger.error("ERROR: No concepts were added to the concept dictionary!")
        # else:
        #     # Log a sample of concepts that were added
        #     sample_concepts = list(self.concept_dict.keys())[:10]
        #     logger.info(f"Sample concepts in dictionary: {sample_concepts}")
        #     logger.info([k for k in self.concept_dict.keys() if "SalesRevenueAutomotive" in k])


    def _get_primary_statement_name(self, pattern):
        """
        Legacy English-keyword lookup. Kept for backwards compatibility only --
        _pick_primary_statement() is the detector now. This matches on the ROLE NAME,
        which only works for English role names and silently returns None for the
        ~40% of EU filings that use IFRS role numbers or local-language names.
        """
        matching_names = [
            sn for sn in self.statement_dimensions.keys()
            if (re.search(pattern, sn.lower()) and
                self._is_primary_statement(sn) and  # Ensure it's a primary statement
                not re.search(_DISCLOSURE_RE, sn.lower()))  # Exclude disclosures
        ]
        # Sort by length to prefer shorter, cleaner names
        matching_names.sort(key=len)
        return matching_names[0] if matching_names else None

    def _promote_picked_statements(self):
        """
        A network chosen as the SOP/SFP/SCF *is* a primary statement, whatever its role
        name looks like.

        _is_primary_statement() runs per-network during _process_taxonomy(), before the
        picks are known, and it vetoes anything whose name contains 'details'/'notes'/etc.
        Some filers suffix their real primary statement that way, so without this pass the
        same network would end up with statement_type='SOP' but is_primary_statement=False.
        Runs before populate_concept_df(), so the DataFrame sees the corrected values.
        """
        for name in (self.name_sop, self.name_sfp, self.name_scf):
            if not name or name not in self.disclosure_concepts:
                continue
            concepts = self.disclosure_concepts.pop(name)
            for concept_info in concepts:  # same dict objects as in self.concept_dict
                concept_info['is_primary_statement'] = True
            self.statement_concepts.setdefault(name, []).extend(concepts)
            logger.debug(f"Promoted '{name}' from disclosure to primary statement")

    def _role_code(self, statement_name):
        """
        The IFRS presentation role NUMBER for a network, e.g. 'ias_1_role-210000' -> '210000'.

        This is the strongest signal available and it is completely language-independent:
        the IFRS taxonomy assigns a fixed number to each primary statement, so a Swedish,
        Polish or Greek filing that uses the standard roles is identified exactly.
        Returns None when the filer used a custom role URI.
        """
        role = self.statement_roles.get(statement_name) or statement_name or ""
        m = _ROLE_CODE_RE.search(role)
        return m.group(1) if m else None

    def _root_kind(self, statement_name):
        """
        The statement type implied by the network's ROOT concept, or None.

        ESEF RTS Article 4 requires every primary statement's presentation network to
        anchor to one of a small set of IFRS abstracts, so the root's local name
        (e.g. 'StatementOfFinancialPositionAbstract') identifies the statement exactly --
        in any language, and regardless of what the filer called the role.
        """
        for root in self.network_roots.get(statement_name, ()):
            kind = _ROOT_CONCEPT_ANCHORS.get(root)
            if kind:
                return kind
        return None

    def _role_pattern_kind(self, statement_name):
        """
        The statement type implied by a curated MULTILINGUAL match on the role name, or
        None. The safety net: it fires only for filings that are neither IFRS-numbered nor
        Article-4 anchored, and it covers the local-language names (Bilanz,
        Kapitalflussrechnung, CompteDeResultat, KoncernensBalansrkning, ...) that an
        English keyword list can never reach.
        """
        for pattern, label in _PRIMARY_ROLE_PATTERNS:
            if pattern.search(statement_name or ""):
                return label
        return None

    def _anchor_scores(self, statement_name):
        """
        Score a network by the IFRS ANCHOR CONCEPTS it contains.

        Language-independent by construction: it ignores the role NAME entirely and looks
        at what the network is made of. A balance sheet contains Assets/Liabilities/Equity
        whatever it is called in the filer's language; a cash flow statement contains
        CashFlowsFromUsedIn*Activities. Returns {kind: n_anchors_present}.
        """
        local_names = {q.split(':')[-1] for q in self.network_concepts.get(statement_name, [])}
        return {kind: len(anchors & local_names) for kind, anchors in _STATEMENT_ANCHORS.items()}

    def _pick_primary_statement(self, kind):
        """
        Choose the single network that IS the SOP / SFP / SCF, in three layers:

          1. exact IFRS role number   -- language-independent, zero ambiguity
          2. anchor-concept scoring   -- language-independent; the kind must be the network's
                                         top-scoring kind and clear _MIN_ANCHORS
          3. English role-name keyword -- last resort, and only for genuinely English roles

        Layer 2's argmax is what stops the statement of comprehensive income being returned
        as the SOP: an OCI network scores higher on OCI than on SOP, so it is excluded.
        (The previous implementation sorted candidates by NAME LENGTH and took the shortest,
        which on English filings really did return the OCI statement as the SOP.)
        """
        # Two-statement or single-statement presentation? (IAS 1.10A -- see _OCI_ROLE_CODES)
        # If the filer numbered a dedicated P&L network, a 4x0000 role is its OCI
        # continuation and must never displace it. If they did not, the 4x0000 combined
        # statement is the only income statement there is, and it IS the SOP.
        has_dedicated_pl = any(self._role_code(n) in _PL_ROLE_CODES
                               for n in self.statement_dimensions)

        best = None
        for name in self.statement_dimensions.keys():
            # A disclosure-sounding NAME demotes a candidate; it does not veto it. Some
            # filers suffix their real primary statement with 'Details'
            # (e.g. 'Statementofcomprehensiveincomeprofitorlossbyfunctionofexpense
            # Details'), and a name heuristic must never overrule structural evidence --
            # otherwise the company's actual P&L is discarded and SOP comes back None.
            looks_like_disclosure = bool(re.search(_DISCLOSURE_RE, name.lower()))

            scores = self._anchor_scores(name)
            score = scores.get(kind, 0)
            code_kind = _IFRS_ROLE_CODES.get(self._role_code(name))
            root_kind = self._root_kind(name)
            name_kind = self._role_pattern_kind(name)

            if code_kind is not None:
                # Layer 1: the filer used a standard IFRS role. Trust it, and let it veto:
                # a network explicitly numbered as OCI/SCE is never the SOP/SFP/SCF --
                # EXCEPT for the single-statement presentation, where the combined
                # statement of comprehensive income is the filing's income statement.
                is_combined_ci = (kind == 'SOP' and code_kind == 'OCI'
                                  and not has_dedicated_pl)
                if code_kind != kind and not is_combined_ci:
                    continue
                rank = 4
            elif root_kind is not None:
                # Layer 2: the ESEF Article 4 root anchor. Also a veto -- a network rooted
                # at StatementOfChangesInEquityAbstract is not the balance sheet.
                if root_kind != kind:
                    continue
                rank = 3
            elif score >= _MIN_ANCHORS and max(scores.values()) == score:
                # Layer 3: the network IS made of this statement's anchors.
                rank = 1 if looks_like_disclosure else 2
            elif not looks_like_disclosure and name_kind == kind:
                # Layer 4: multilingual role-name match -- the last-resort safety net.
                rank = 0
            else:
                continue

            # Prefer a stronger layer, then more anchors, then the shorter (cleaner) name.
            cand = (rank, score, -len(name), name)
            if best is None or cand > best:
                best = cand

        if best is not None:
            logger.debug(f"{kind} -> {best[3]} (layer={best[0]}, anchors={best[1]})")
            return best[3]
        return None
    def _process_taxonomy(self):
        """Process taxonomy to build concept dictionaries"""
        logger.info("Processing taxonomy presentation networks")
        
        networks = TaxonomyPresentation.get_presentation_networks(self.tax)
        logger.info(f"\nFound {len(networks)} presentation networks")

        if not networks:
            logger.warning("No presentation networks found. Adding all concepts to unknown disclosure.")
            # Add all concepts as disclosures under "Unknown"
            self.disclosure_concepts["Unknown"] = []
            for qname, concept in self.tax.concepts_by_qname.items():
                label = concept.get_label() if hasattr(concept, 'get_label') else None
                concept_info = {
                    "concept_name": concept.name,
                    "concept_qname": str(qname),
                    "label": label,
                    "statement_name": "Unknown",
                    "statement_role": None,
                    "is_primary_statement": False
                }
                self.disclosure_concepts["Unknown"].append(concept_info)
                self.concept_dict[str(qname)] = concept_info
            return
        
        # Process each network
        for network in networks:
            statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
            # Keep the FULL role URI: the IFRS role number lives in it, and it is the only
            # language-independent way to identify a statement.
            self.statement_roles[statement_name] = getattr(network, 'role', None)

            # Process network dimensions
            self._process_network_dimensions(network, statement_name)

            # Get concepts using reporter for labels
            concepts = get_network_details(self.tax, network, self.reporter)
            logger.debug(f"Found {len(concepts)} concepts in network")

            # Record the network's concepts BEFORE classifying it: anchor scoring needs to
            # know what the network is made of, so is_primary cannot be decided from the
            # name alone (which is what silently lost the ~40% of non-English filings).
            self.network_concepts[statement_name] = [c['qname'] for c in concepts]
            # The ROOT concept of the network. ESEF RTS Article 4 requires a primary
            # statement to anchor to a known IFRS abstract, so the root names the
            # statement type exactly, in any language.
            self.network_roots[statement_name] = {
                str(c['qname']).split(':')[-1] for c in concepts if not c.get('parent_qname')
            }
            is_primary = self._is_primary_statement(statement_name)
            if is_primary:
                logger.debug(f"\nProcessing network: {statement_name} (Primary: {is_primary})")

            # Initialize lists for this network if not already present
            target_dict = self.statement_concepts if is_primary else self.disclosure_concepts
            if statement_name not in target_dict:
                target_dict[statement_name] = []
            
            # Add concepts to appropriate network list
            for concept in concepts:
                concept_qname = concept['qname']
                
                # Get segment/dimension information from the statement_dimensions
                segment_info = self.statement_dimensions.get(statement_name, {})
                dimensions = segment_info.get('dimensions', set())
                members = segment_info.get('members', {})
                
                # Create base concept info
                concept_info = {
                    "concept_name": concept['name'],
                    "concept_qname": concept_qname,
                    "label": concept['label'],
                    "order": concept.get('order'),
                    "parent_qname": concept.get('parent_qname'),
                    "statement_name": statement_name,
                    "statement_role": network.role if hasattr(network, 'role') else None,
                    "is_primary_statement": is_primary,
                    # Add segment information
                    "segment_axes": list(dimensions),
                    "segment_members": {str(dim): list(mems) for dim, mems in members.items()},
                    "has_dimensions": len(dimensions) > 0,
                    "dimension_count": len(dimensions)
                }
                
                # For each dimension, create a separate concept entry with segment info
                if dimensions:
                    for dimension in dimensions:
                        dimension_members = members.get(dimension, [])
                        for member in dimension_members:
                            segment_concept_info = concept_info.copy()
                            segment_concept_info.update({
                                "segment_axis": str(dimension),
                                "segment_axis_member": str(member),
                                "segment_dimension": str(dimension),
                                "segment_dimension_member": str(member)
                            })
                            target_dict[statement_name].append(segment_concept_info)
                            # Also maintain in flat concept dictionary
                            key = f"{concept_qname}_{dimension}_{member}"
                            self.concept_dict[key] = segment_concept_info
                else:
                    # Add the concept without segment information
                    concept_info.update({
                        "segment_axis": None,
                        "segment_axis_member": None,
                        "segment_dimension": None,
                        "segment_dimension_member": None
                    })
                    target_dict[statement_name].append(concept_info)
                    self.concept_dict[concept_qname] = concept_info
        
        # Merge dictionaries with priority to statements
        self.concept_dict.update(self.disclosure_concepts)  # Add disclosures first
        self.concept_dict.update(self.statement_concepts)  # Override with statements
        
        # Debug: Final check for SalesRevenueAutomotive
        for dict_name, concepts_dict in [("statement_concepts", self.statement_concepts), 
                                       ("disclosure_concepts", self.disclosure_concepts),
                                       ("concept_dict", self.concept_dict)]:
            for qname in concepts_dict:
                if 'SalesRevenueAutomotive' in qname:
                    logger.debug(f"Found SalesRevenueAutomotive in {dict_name}: {qname}")
        
        logger.info(f"\nProcessed {len(self.statement_concepts)} statement concepts and {len(self.disclosure_concepts)} disclosure concepts")

    @staticmethod
    def get_presentation_networks(taxonomy):
        """Extracts presentation networks from a taxonomy by examining linkbases and base sets"""
        logger.info("\nAccessing presentation networks...")
        
        # First check if presentation linkbases are loaded
        presentation_linkbases = []
        presentation_networks = []
        for lb_location, lb in taxonomy.linkbases.items():
            # Check if this is a presentation linkbase by looking at the file name
            if '_pre.xml' in lb_location.lower():
                presentation_linkbases.append(lb)
                #logger.info(f"Found presentation linkbase: {lb_location}")
                # Debug information about the linkbase
                #logger.info(f"Linkbase type: {type(lb)}, attributes: {dir(lb)}")
                # if hasattr(lb, 'links'):
                #     logger.info(f"Number of links: {len(lb.links)}")
                    #for link in lb.links:
                    #    #logger.debug(f"Link type: {type(link)}, tag: {getattr(link, 'tag', 'No tag')}")
                
        #(threshold_gb=16)
        logger.info(f"Found {len(presentation_linkbases)} presentation linkbases")
        
        # Check if the taxonomy object has base_sets
        if hasattr(taxonomy, 'base_sets'):
            logger.info(f"Number of base_sets: {len(taxonomy.base_sets)}")
            
            presentation_networks = []
            # First try to get networks from base_sets
            for key, base_set in taxonomy.base_sets.items():
                if isinstance(key, tuple) and len(key) >= 3:
                    arc_name, role, arcrole = key
                    if 'presentation' in str(arc_name).lower():
                        #logger.debug(f"Found presentation base_set: {key}")
                        presentation_networks.append(base_set)
                elif isinstance(key, str) and 'presentation' in key.lower():
                    #logger.debug(f"Found presentation base_set: {key}")
                    presentation_networks.append(base_set)
            #(threshold_gb=16)
            if not presentation_networks:
                logger.warning("No presentation networks found in base_sets")
                
                # Try to build networks from presentation linkbases
                if presentation_linkbases:
                    logger.info("Building networks from presentation linkbases...")
                    for lb in presentation_linkbases:
                        if hasattr(lb, 'links'):
                            for link in lb.links:
                                # Add the link itself as a network
                                if 'presentation' in str(getattr(link, 'tag', '')).lower():
                                    presentation_networks.append(link)
                                    logger.debug("Added presentation link to networks")
                                
                                # Also add any presentation arcs
                                if hasattr(link, 'arcs'):
                                    for arc in link.arcs:
                                        if 'presentation' in str(getattr(arc, 'tag', '')).lower():
                                            presentation_networks.append(arc)
                                            logger.debug("Added presentation arc to networks")
                    
                    if presentation_networks:
                        logger.info(f"Built {len(presentation_networks)} networks from linkbases")
                        return presentation_networks
                #(threshold_gb=16)
                # If still no networks, try compilation
                if hasattr(taxonomy, 'compile_presentation_networks'):
                    logger.info("Attempting to compile presentation networks...")
                    networks = taxonomy.compile_presentation_networks()
                    if networks:
                        logger.info(f"Compilation yielded {len(networks)} networks")
                        return networks
            
            return presentation_networks
        else:
            logger.error("No base_sets found in taxonomy")
            return []

    def _process_network_dimensions(self, network, statement_name):
        concepts = get_network_details(self.tax, network, self.reporter)
        concept_dict = {concept['qname']: concept for concept in concepts}
        for concept in concepts:
            parent_qname = concept.get('parent_qname')
            if parent_qname:
                parent_concept = concept_dict.get(parent_qname)
                if parent_concept:
                    if 'children' not in parent_concept:
                        parent_concept['children'] = []
                    parent_concept['children'].append(concept)
        root_concepts = [concept for concept in concepts if not concept.get('parent_qname')]
        allowed_dimensions = set()
        allowed_members = {}
        
        def process_table_structure(node_dict, current_dimension=None, _path=None):
            if not node_dict:
                return
            node_name = node_dict.get('qname', str(node_dict))
            # Branch-scoped guard: a cyclic presentation chain (A parent of B, B parent of A)
            # would otherwise recurse forever, the same way cyclic calculation arcs do.
            if _path is None:
                _path = set()
            if node_name in _path:
                logger.warning("Cyclic presentation relationship pruned at %s (statement %s)",
                               node_name, statement_name)
                return
            _path.add(node_name)
            if 'Axis' in node_name:
                dimension = node_name
                allowed_dimensions.add(dimension)
                allowed_members[dimension] = set()
                current_dimension = dimension
                logger.debug(f"Found dimension: {dimension}")
            if current_dimension and 'Member' in node_name:
                allowed_members[current_dimension].add(node_name)
                logger.debug(f"Added member {node_name} to dimension {current_dimension}")
            try:
                for child_dict in node_dict.get('children', []):
                    process_table_structure(child_dict, current_dimension, _path)
            finally:
                _path.discard(node_name)  # pop on exit: keeps _path branch-scoped

        for root in root_concepts:
            process_table_structure(root)
        
        
        self.statement_dimensions[statement_name] = {
            'dimensions': allowed_dimensions,
            'members': allowed_members
        }

    def populate_concept_df(self):
        """Creates DataFrame from concept dictionaries and adds calculation information"""
        # Flatten the nested dictionaries into a list of concept infos
        all_concepts = []
        
        # Add statement concepts
        for statement_name, concepts in self.statement_concepts.items():
            all_concepts.extend(concepts)
            
        # Add disclosure concepts
        for disclosure_name, concepts in self.disclosure_concepts.items():
            all_concepts.extend(concepts)
            
        # Create DataFrame
        if all_concepts:
            import pandas as pd
            self.concept_df = pd.DataFrame(all_concepts)
            self.concept_df.loc[:, 'statement_type'] = self.concept_df['statement_name'].map(self.statement_types)
            
            # Ensure segment columns exist
            segment_columns = [
                'segment_axis', 'segment_axis_member',
                'segment_dimension', 'segment_dimension_member',
                'has_dimensions', 'dimension_count'
            ]
            for col in segment_columns:
                if col not in self.concept_df.columns:
                    self.concept_df.loc[:, col] = None
            
            # Create enhanced link_df with segment information
            self.link_df = self.concept_df.copy()
            
            # Add calculation information
            calc_df = tax_calc_df(self.tax)
            if not calc_df.empty:
                # First normalize statement names in both DataFrames
                self.link_df.loc[:, 'statement_name_norm'] = self.link_df['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
                calc_df.loc[:, 'role_name_norm'] = calc_df['role_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
                
                # Group calculation relationships by role and concept
                calc_by_role_parent = calc_df.groupby(['role_name_norm', 'from_qname'])[['to_qname', 'weight']].apply(
                    lambda x: dict(zip(x['to_qname'], x['weight']))
                ).to_dict()
                
                calc_by_role_child = calc_df.groupby(['role_name_norm', 'to_qname'])[['from_qname', 'weight']].apply(
                    lambda x: dict(zip(x['from_qname'], x['weight']))
                ).to_dict()
                
                # Now add calculation flags
                self.link_df.loc[:, 'is_calc_parent'] = self.link_df.apply(
                    lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_parent, 
                    axis=1
                )
                
                self.link_df.loc[:, 'is_calc_child'] = self.link_df.apply(
                    lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_child, 
                    axis=1
                )
                
                # Add calculation role information
                def get_calc_roles(row, calc_df):
                    return list(calc_df[
                        (calc_df['from_qname'] == row['concept_qname']) | 
                        (calc_df['to_qname'] == row['concept_qname'])
                    ]['role_name'].unique())
                
                self.link_df.loc[:, 'calc_roles'] = self.link_df.apply(
                    lambda row: get_calc_roles(row, calc_df), axis=1
                )
                
                # Add detailed calculation relationships
                def get_calc_details(row):
                    key = (row['statement_name_norm'], row['concept_qname'])
                    children = calc_by_role_parent.get(key, {})
                    parents = calc_by_role_child.get(key, {})
                    
                    return {
                        'calc_children': list(children.keys()),
                        'calc_parents': list(parents.keys()),
                        'calc_children_weights': [v for k, v in children.items()],
                        'calc_children_weights_str': ' + '.join([f"({v:+g}) * {k}" for k, v in children.items()]) if children else '',
                        'calc_children_weights_dict': children,
                        'calc_parents_weights': [v for k, v in parents.items()],
                        'calc_parents_weights_str': ' + '.join([f"({v:+g}) * {k}" for k, v in parents.items()]) if parents else '',
                        'calc_parents_weights_dict': parents,
                        'num_calc_children': len(children),
                        'num_calc_parents': len(parents),
                        'is_summation': len(children) > 1,  # Concept sums multiple children
                        'is_component': len(parents) > 0,   # Concept is part of a sum
                        'has_negative_weight': any(v < 0 for v in children.values()) or any(v < 0 for v in parents.values()),
                        'all_positive_weights': all(v > 0 for v in children.values()) and all(v > 0 for v in parents.values()),
                        'weight_types': ', '.join(set(
                            [f"child:{v:+g}" for v in children.values()] + 
                            [f"parent:{v:+g}" for v in parents.values()]
                        ))
                    }
                
                # Apply calculation details to DataFrame
                calc_details = self.link_df.apply(get_calc_details, axis=1)
                for col, values in pd.DataFrame(calc_details.tolist()).items():
                    self.link_df.loc[:, col] = values
                
                # Add calculation hierarchy information
                def get_calc_hierarchy_info(row, calc_df):
                    concept = row['concept_qname']
                    role_matches = calc_df[calc_df['role_name_norm'] == row['statement_name_norm']]
                    
                    # Find all ancestors (parents of parents)
                    def get_ancestors(qname, visited=None):
                        if visited is None:
                            visited = set()
                        if qname in visited:
                            return set()
                        visited.add(qname)
                        parents = set(role_matches[role_matches['to_qname'] == qname]['from_qname'])
                        ancestors = set()
                        for parent in parents:
                            ancestors.update(get_ancestors(parent, visited))
                        return parents.union(ancestors)
                    
                    # Find all descendants (children of children)
                    def get_descendants(qname, visited=None):
                        if visited is None:
                            visited = set()
                        if qname in visited:
                            return set()
                        visited.add(qname)
                        children = set(role_matches[role_matches['from_qname'] == qname]['to_qname'])
                        descendants = set()
                        for child in children:
                            descendants.update(get_descendants(child, visited))
                        return children.union(descendants)
                    
                    ancestors = get_ancestors(concept)
                    descendants = get_descendants(concept)
                    
                    return {
                        'calc_ancestors': list(ancestors),
                        'calc_descendants': list(descendants),
                        'calc_hierarchy_level': len(ancestors),  # Number of levels above this concept
                        'is_calc_root': len(ancestors) == 0 and len(descendants) > 0,  # Top-level calculation concept
                        'is_calc_leaf': len(descendants) == 0 and len(ancestors) > 0,  # Bottom-level calculation concept
                    }
                
                # Apply calculation hierarchy information
                hierarchy_info = self.link_df.apply(
                    lambda row: get_calc_hierarchy_info(row, calc_df), axis=1
                )
                for col, values in pd.DataFrame(hierarchy_info.tolist()).items():
                    self.link_df.loc[:, col] = values
                
                #logger.debug(f"Added enhanced calculation information to link_df")
        else:
            logger.warning("No concepts found to create DataFrame")

    def is_valid_concept(self, concept_qname):
        """
        Checks if a concept exists in any presentation network.
        
        Args:
            concept_qname: The QName of the concept to check
            
        Returns:
            bool: True if concept exists in any network, False otherwise
        """
        # Check in flat concept dictionary for quick lookup
        return concept_qname in self.concept_dict
        
    def get_concept_info(self, concept_qname):
        """
        Gets detailed information about a concept.
        
        Args:
            concept_qname: The QName of the concept
            
        Returns:
            dict: Concept information including network context, or None if not found
        """
        # First try quick lookup in concept_dict
        if concept_qname in self.concept_dict:
            return self.concept_dict[concept_qname]
            
        # If not found, do an exhaustive search through all networks
        # This is a fallback in case concept_dict is not in sync
        for statement_name, concepts in self.statement_concepts.items():
            for concept in concepts:
                if concept['concept_qname'] == concept_qname:
                    return concept
                    
        for disclosure_name, concepts in self.disclosure_concepts.items():
            for concept in concepts:
                if concept['concept_qname'] == concept_qname:
                    return concept
                    
        return None
        
    def get_concepts_by_statement(self, statement_name):
        """
        Gets all concepts for a specific statement/disclosure.
        
        Args:
            statement_name: Name of the statement or disclosure
            
        Returns:
            list: List of concept information dictionaries, or empty list if not found
        """
        # Check in statement concepts first
        if statement_name in self.statement_concepts:
            return self.statement_concepts[statement_name]
            
        # Then check in disclosure concepts
        if statement_name in self.disclosure_concepts:
            return self.disclosure_concepts[statement_name]
            
        return []
        
    def get_statement_names(self):
        """
        Gets all statement names in the taxonomy.
        
        Returns:
            list: List of statement names
        """
        return list(self.statement_concepts.keys())
        
    def get_disclosure_names(self):
        """
        Gets all disclosure names in the taxonomy.
        
        Returns:
            list: List of disclosure names
        """
        return list(self.disclosure_concepts.keys())

    def __str__(self):
        return self.info()

    def __repr__(self):
        return self.info()

    def info(self):
        info_str = '\n'.join([
            f'TaxonomyPresentation object with {len(self.concept_dict)} concepts',
            f'Taxonomy: {self.tax}',
            f'Reporter: {self.reporter}',
            f'Concept DataFrame: {self.concept_df.shape if self.concept_df is not None else "None"}' + f'{self.concept_df.head(30).to_string()}'
        ])  
        if self.name_sop:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nIncome Statement: {self.name_sop}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.name_sop].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo income statement found'
        if self.name_sfp:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nBalance Sheet: {self.name_sfp}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.name_sfp].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo balance sheet found'
        if self.name_scf:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nCash Flow: {self.name_scf}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.name_scf].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo cash flow statement found'
        return info_str
    
    def _is_primary_statement(self, role_name):
        """
        Determine if a role represents a primary statement.

        Three independent ways to say yes, because the role NAME alone is not a reliable
        signal outside English filings:

          1. the IFRS role NUMBER says so (language-independent, exact);
          2. the network CONTAINS a primary statement's anchor concepts
             (language-independent -- a Bilanz still contains Assets and Liabilities);
          3. the English keyword test (the original rule, kept as a fallback).

        The old rule was (1)-blind and (2)-blind: it required the role name to contain the
        literal substring 'statement'/'balancesheet'/'coverpage'/'consolidate', so a role
        named 'ias_1_role-210000' -- a perfectly standard IFRS balance sheet -- was filed
        as a DISCLOSURE. That is why ~19% of filings reported no primary statements at all.
        """
        role_lower = (role_name or "").lower()

        disclosure_keywords = [r'disclosure', r'notes', r'details', r'schedule', r'policies', "table"]
        if any(re.search(k, role_lower, flags=re.IGNORECASE) for k in disclosure_keywords):
            return False

        # 1. IFRS role number
        if _IFRS_ROLE_CODES.get(self._role_code(role_name)) is not None:
            return True

        # 2. ESEF Article 4 root-concept anchor
        if self._root_kind(role_name) is not None:
            return True

        # 3. Anchor concepts
        scores = self._anchor_scores(role_name)
        if scores and max(scores.values()) >= _MIN_ANCHORS:
            return True

        # 4. Multilingual role-name match (Bilanz, Kapitalflussrechnung, ...)
        if self._role_pattern_kind(role_name) is not None:
            return True

        # 5. English keywords (original behaviour)
        statement_keywords = [r'balance', r'operations', r'income', r'cash flow', r'cashflow', r'equity', r'financial position', r'financialposition', r'statement', r'DocumentAndEntityInformation']
        return any(
            re.search(keyword, role_lower, flags=re.IGNORECASE) for keyword in statement_keywords) and \
            bool(re.search("Statement|DocumentAndEntityInformation|balancesheet|coverpage|consolidate", role_lower, flags=re.IGNORECASE))


    def _validate_segment(self, segment_data, statement_name):
        """
        Validate segment data against statement's allowed dimensions.
        A fact with dimensions should only be included in a statement if:
        1. The statement allows dimensions AND
        2. The specific dimensions and members are allowed in that statement
        Otherwise, the fact belongs in disclosures.
        
        Args:
            segment_data: Dictionary of dimension:member pairs
            statement_name: Name of the statement to validate against
            
        Returns:
            bool: True if segment is valid for this statement, False otherwise
        """
        # If no segment data, fact is valid for primary statement
        if not segment_data:
            return True
            
        # Get allowed dimensions and members for this statement
        statement_dims = self.statement_dimensions.get(statement_name, {})
        allowed_dimensions = statement_dims.get('dimensions', set())
        allowed_members = statement_dims.get('members', {})
        
        # For each dimension in the segment data
        for dimension, member in segment_data.items():
            # Check if dimension is allowed
            if dimension not in allowed_dimensions:
                return False
                
            # Check if member is allowed for this dimension
            if dimension in allowed_members:
                if member not in allowed_members[dimension]:
                    return False
                    
        return True

    def is_valid_segment(self, concept_qname, segment_data, statement_name=None):
        """
        Check if a segment is valid for a concept in a specific statement context.
        
        Args:
            concept_qname: The concept's QName
            segment_data: Dictionary of dimension:member pairs
            statement_name: Optional statement name to check against
            
        Returns:
            bool: True if the segment is valid for this concept/statement combination
        """
        if not statement_name:
            # If no statement specified, check all statements
            for statement in self.statement_concepts:
                if self._validate_segment(segment_data, statement):
                    return True
            for disclosure in self.disclosure_concepts:
                if self._validate_segment(segment_data, disclosure):
                    return True
            return False
            
        # Validate against specific statement
        return self._validate_segment(segment_data, statement_name)

#Prompt: Please help me accommodate unclassified_concepts into my class StatementOfOperations by updating PATTERNS and EXACT_MATCHES. All the unclassified concepts need to be mapped into the predefined accounts and sections with exact matches and patterns.  
class StatementOfOperations:
    """Class encapsulating Statement of Operations (SOP) constants and patterns.

    Statement of Operations Sections Definition:
    - Top section (1. `REV_COGS_GP`) : revenues (`REV`), cost of goods sold (`COGS`), gross profit (`GP`)
        - Revenue 
        - COGS and gross profit 
    - Middle section I (2. `OP_EXP_OP_INC`) : operating expenses, operating income
        - Operating income 
        - Operating expenses 
    - Middle section II (3. `INT_SPI_PRET`) : interest income/expense, special items, pretax income
        - Special items below operating section
        - Interest and tax items 
    - Bottom section I (4. `TAXES_NI_MINORITY`) : income taxes, net income, minority interest
        - Interest and tax items 
        - Net income 
        - Minority interest 
    - Bottom section II (5. `EPS`) : EPS
        - Primary and diluted EPS 

    """
    
    # Ordered list of sections in the statement
    SECTIONS = [
        'REV_COGS_GP',           # Revenue, Cost of Goods Sold, Gross Profit
        'OP_EXP_OP_INC',         # Operating Expenses and Income
        'INT_SPI_PRET',      # Interest, Special Items, Pretax Income
        'TAXES_NI_MINORITY',  # Interest, Special Items, Pretax, Taxes, Net Income
        'EPS'        # Net Income, Minority Interest, EPS
    ]
    
    # Mapping of exact US-GAAP concept matches to account types
    EXACT_MATCHES = {
        'REV': [
            'us-gaap:Revenues',
            'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
            'us-gaap:SalesRevenueNet',
            'us-gaap:SalesRevenueGoodsNet',
            'us-gaap:RevenueFromContractWithCustomer'
        ],
        'COGS': [
            'us-gaap:CostOfGoodsAndServicesSold',
            'us-gaap:CostOfRevenue',
            'us-gaap:CostOfGoodsSold',
            'us-gaap:CostOfServices'
        ],
        'GP': [
            'us-gaap:GrossProfit',
            'us-gaap:GrossMargin'
        ],
        'OP_EXP': [
            'us-gaap:OperatingExpenses',
            'us-gaap:SellingGeneralAndAdministrativeExpense',
            'us-gaap:ResearchAndDevelopmentExpense',
            'us-gaap:DepreciationDepletionAndAmortization',
            'us-gaap:ProvisionForDoubtfulAccounts',
            'us-gaap:BusinessCombinationAcquisitionAndIntegrationCosts',
            'us-gaap:MarketingExpense',
            'us-gaap:AdvertisingExpense'
        ],
        'OP_INC': [
            'us-gaap:OperatingIncomeLoss',
            'us-gaap:IncomeLossFromContinuingOperations',
            'us-gaap:IncomeLossFromOperations'
        ],
        'SPI': [
            'us-gaap:GainsLossesOnExtinguishmentOfDebt',
            'us-gaap:ImpairmentOfInvestments',
            'us-gaap:GainLossOnSaleOfOtherAssets',
            'us-gaap:AssetImpairmentCharges',
            'us-gaap:RestructuringCosts',
            'us-gaap:NonoperatingIncomeExpense',
            'us-gaap:IncomeLossFromEquityMethodInvestments',
            'us-gaap:GainLossOnInvestments',
            'us-gaap:GainLossOnDispositionOfAssets',
            'us-gaap:BusinessCombinationAcquisitionRelatedCosts'
        ],
        'PRET': [
            'us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
            'us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes'
        ],
        'TAX': [
            'us-gaap:IncomeTaxExpenseBenefit',
            'us-gaap:IncomeTaxesPaid',
            'us-gaap:IncomeTaxesPaidNet'
        ],
        'NI': [
            'us-gaap:NetIncomeLoss',
            'us-gaap:ProfitLoss',
            'us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic'
        ],
        'MIN_INT': [
            'us-gaap:NetIncomeLossAttributableToNoncontrollingInterest',
            'us-gaap:IncomeLossAttributableToNoncontrollingInterest'
        ],
        'EPS': [
            'us-gaap:EarningsPerShareBasic',
            'us-gaap:EarningsPerShareDiluted',
            'us-gaap:WeightedAverageNumberOfSharesOutstandingBasic',
            'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding'
        ]
    }
    
    # Regex patterns for fuzzy matching concept names and labels
    PATTERNS = {
        'REV': [
            r'revenue', r'sale.*net', r'turnover', r'fee.*income', 
            r'net.*sales',  
            # this is not revenue: r'operating.*income(?!.*expense)',
            r'contract.*revenue', r'service.*revenue'
        ],
        'COGS': [
            r'cost.*good.*sold', r'cost.*revenue', r'cost.*sale', 
            r'direct.*cost', r'product.*cost', r'cost.*service'
        ],
        'GP': [
            r'gross.*profit', r'gross.*margin', r'gross.*income',r'profit.*before.*operating'
        ],
        'OP_EXP': [
            r'operating.*expense', r'selling.*expense', r'general.*administrative',
            r'marketing', r'research.*development', r'depreciation',
            r'amortization', r'sg.*a', r'labor.*expense', r'personnel.*cost',
            r'advertising.*expense',
            r'expense', r"cost",
            r'professional.*fee',
            r'legal.*fee',
            r'accounting.*fee',
            r'utilities',
            r'rent',
            r'salaries.*wages',
            r'compensation',
            r'travel',
            r'communication',
            r'occupancy',
            r'insurance',
            r'taxes',
            r'maintenance',
            r'bank.*charges',
            r'data.*processing',
            r'service.*fees',
            r'director.*fee',
            r'administrative.*fee',
            r'facility.*action',

        ],
        'OP_INC': [
            r'operating.*income', r'operating.*profit', r'operating.*earning',
            r'operating.*loss', r'income.*from.*operation', r'operating.*result'
        ],
        'INT_INC': [
            r'interest.*income', r'interest.*revenue', r'investment.*income', r'other.*income'
        ],
        'INT_EXP': [
            r'interest.*expense', r'interest.*cost', r'financing.*cost',
            r'preferred.*stock.*dividends',
        ],
        'SPI': [
            r'special.*item', r'extraordinary.*', r'unusual.*', r'restructuring.*',
            r'discontinued.*operation', r'impairment.*', r'disposal.*', 
            r'write.*off', r'write.*down', r'gain.*sale', r'loss.*sale', r"gain.*loss", r'gainon', r'losson',
            r'other.*income', r'other.*expense', r'other.*gain', r'other.*loss',
            r'equity.*earning', r'equity.*loss', r'debt.*extinguishment',
            r'acquisition.*related.*cost', r'integration.*cost',
            r"adjustment",
            r'change.*fair.*value'
            r'provision.*credit.*loss', r'provision.*doubtful.*account',
            r'acquisition.*integration.*cost', 
            r'regulatory.*assessment',
            r'foreclosure',
            r'settlement',
            r'loss.*contingency',
            r'bargain.*purchase',
            r'currency.*translation',
            r'reorganization',
            r'litigation',
            r'casualty',
            r'derivatives',
            r'goodwill|intangible|asset|liabilit',
            r'loss.*disposition',
            r'loss.*termination',
            r'premium.*amortization',
            r'prepayment.*penalty',
            r'debt.*forgiveness',
            r'asset.*retirement',
            r'modification.*debt',
            r'inventory.*obsolete',
            r'provision'
        ],
        'PRET': [
            r'.*before.*tax.*', r'pretax.*income', r'pre.*tax.*income',
            r'income.*before.*tax', r'earning.*before.*tax'
        ],
        'TAX': [
            r'income.{0,5}tax.*', r'tax.{0,5}expense', r'tax.{0,5}benefit', 
            r'tax.{0,5}provision', r'deferred.{0,5}tax', r'tax.{0,5}paid'
        ],
        'NI': [
            r'net.{0,5}income', r'net.{0,5}loss', r'profit.{0,5}loss', r'net.{0,5}earning',
            r'net.{0,5}result', r'income.{0,5}after.{0,5}tax', r'net.{0,5}profit'
        ],
        'MIN_INT': [
            r'minority.*interest', r'non.*controlling.*interest', 
            r'attributable.*to.*non.*controlling'
        ],
        'EPS': [
            r'per.*share', r'earnings.*per.*share', r'.*eps.*',
            r'diluted.*share', r'basic.*share', r'weighted.*average.*share'
        ]
    }

    
    
    # Mapping of account types to their sections; ALWAYS CHECK MAPPING CONSISTENCY AFTER UPDATING
    ACCOUNT_TYPE_TO_SECTION = {

        # - Top section (1. `REV_COGS_GP`) : revenues (`REV`), cost of goods sold (`COGS`), gross profit (`GP`)

        'REV': 'REV_COGS_GP',
        'COGS': 'REV_COGS_GP',
        'GP': 'REV_COGS_GP',
        
        # - Middle section I (2. `OP_EXP_OP_INC`) : operating expenses, operating income

        'OP_EXP': 'OP_EXP_OP_INC',
        'OP_INC': 'OP_EXP_OP_INC',

        # - Middle section II (3. `INT_SPI_PRET`) : interest income/expense, special items, pretax income

        'INT_INC': 'INT_SPI_PRET',
        'INT_EXP': 'INT_SPI_PRET',
        'SPI': 'INT_SPI_PRET',
        'PRET': 'INT_SPI_PRET',

        # - Bottom section I (4. `TAXES_NI_MINORITY`) : income taxes, net income, minority interest

        'TAX': 'TAXES_NI_MINORITY',
        'NI': 'TAXES_NI_MINORITY',
        'MIN_INT': 'TAXES_NI_MINORITY',

        # - Bottom section II (5. `EPS`) : EPS

        'EPS': 'EPS'
    }
    
    @staticmethod
    def matches_pattern(text, pattern_list):
        """Check if text matches any pattern in the list."""
        if not isinstance(text, str):
            return False
        text = text.lower().replace('_', '').replace('-', '')
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in pattern_list)
    
    @classmethod
    def get_section_for_account_type(cls, account_type):
        """Get the section for a given account type."""
        return cls.ACCOUNT_TYPE_TO_SECTION.get(account_type)
    
    @classmethod
    def is_valid_section(cls, section):
        """Check if a section name is valid."""
        return section in cls.SECTIONS
    
    @classmethod
    def is_valid_account_type(cls, account_type):
        """Check if an account type is valid."""
        return account_type in cls.ACCOUNT_TYPE_TO_SECTION


def get_network_details(tax, network, reporter=None):
    """Processes a presentation network to extract concept details and relationships."""
    concepts = []
    statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
    logger.debug(f"Extracting details from network: {statement_name}")
    
    try:
        if isinstance(network, XLink):
            logger.debug("Processing XLink network")
            concepts_by_label = {}
            concept_info_by_qname = {}  # Track concept info by qname to avoid duplicates
            
            # Process locators to get concepts
            if hasattr(network, 'locators'):
                for label, loc in network.locators.items():
                    if re.search("mem:\/\w", loc.href):
                        loc.href = re.sub(r'mem:\/', 'mem://', loc.href)
                    concept = tax.get_concept_by_href(loc.href)
                    if concept:
                        concepts_by_label[label] = concept
                        # Also store with _lbl suffix for label lookup
                        concepts_by_label[f"{label}_lbl"] = concept
                        
                        # Add concept info for each locator concept
                        concept_qname = str(concept.qname)
                        if concept_qname not in concept_info_by_qname:
                            concept_info = {
                                'name': concept.name,
                                'qname': concept_qname,
                                'label': concept.get_label() if hasattr(concept, 'get_label') else 'N/A',
                                'order': None,  # Will be updated from arc if found
                                'parent_qname': None,  # Will be updated from arc if found
                                'preferred_label': None  # Will be updated from arc if found
                            }
                            concept_info_by_qname[concept_qname] = concept_info
                            concepts.append(concept_info)
            
            # Process arcs to update relationships and orders
            if hasattr(network, 'arcs_from'):
                for arc_from, arc_list in network.arcs_from.items():
                    for arc in arc_list:
                        from_concept = (concepts_by_label.get(arc.xl_from) or 
                                      concepts_by_label.get(f"{arc.xl_from}_lbl"))
                        to_concept = (concepts_by_label.get(arc.xl_to) or 
                                    concepts_by_label.get(f"{arc.xl_to}_lbl"))
                        
                        if from_concept and to_concept:
                            to_qname = str(to_concept.qname)
                            from_qname = str(from_concept.qname)
                            
                            # Update concept info with relationship details
                            if to_qname in concept_info_by_qname:
                                concept_info_by_qname[to_qname].update({
                                    'order': getattr(arc, 'order', None),
                                    'parent_qname': from_qname,
                                    'preferred_label': getattr(arc, 'preferred_label', None)
                                })
                            
                            # Ensure from_concept info is also present
                            if from_qname not in concept_info_by_qname:
                                concept_info = {
                                    'name': from_concept.name,
                                    'qname': from_qname,
                                    'label': from_concept.get_label() if hasattr(from_concept, 'get_label') else 'N/A',
                                    'order': None,
                                    'parent_qname': None,
                                    'preferred_label': None
                                }
                                concept_info_by_qname[from_qname] = concept_info
                                concepts.append(concept_info)
            
            # Sort concepts by order if available
            concepts.sort(key=lambda x: float(x['order']) if x['order'] is not None else float('inf'))
            
            return concepts
        
        # Handle BaseSet objects (from compile_linkbases Pass 2)
        from openesef.taxonomy.base_set import BaseSet
        if isinstance(network, BaseSet):
            logger.debug(f"Processing BaseSet network: {statement_name}")
            members = network.get_members(include_head=True)
            for node in members:
                concept = node.Concept
                concept_qname = str(concept.qname)
                concept_info = {
                    'name': concept.name,
                    'qname': concept_qname,
                    'label': concept.get_label() if hasattr(concept, 'get_label') else 'N/A',
                    'order': float(node.Arc.order) if node.Arc and node.Arc.order is not None else None,
                    'parent_qname': None,
                    'preferred_label': getattr(node.Arc, 'preferredLabel', None) if node.Arc else None
                }
                # Derive parent from chain_up
                bs_key = network.get_key()
                chain_up = concept.chain_up.get(bs_key, [])
                if chain_up:
                    concept_info['parent_qname'] = str(chain_up[0].Concept.qname)
                concepts.append(concept_info)

            concepts.sort(key=lambda x: float(x['order']) if x['order'] is not None else float('inf'))
            return concepts

        logger.warning(f"Network {statement_name} is not an XLink or BaseSet instance")
        return []

    except Exception as e:
        logger.error(f"Error processing network {statement_name}: {str(e)}")
        logger.debug("Exception details:", exc_info=True)
        return []

def analyze_statement_section(section_facts, fact_df, section_name="SOP"):
    """
    Analyze a specific section of a statement, providing metrics about its composition and complexity.
    
    Args:
        section_facts (pd.DataFrame): DataFrame containing facts for the specific section
        fact_df (pd.DataFrame): Complete fact DataFrame for additional context
        section_name (str): Name of the section being analyzed
        
    Returns:
        dict: Analysis results including:
            - num_line_items: Total number of line items in the section
            - num_non_standard: Number of non-standard (non-us-gaap) concepts
            - num_with_axes: Number of facts using axes
            - num_with_dimensions: Number of facts using dimensions
            - top_concepts: List of top 5 concepts by absolute value
            - section_size: Total absolute value of all facts in section
            - relative_size: Size relative to total statement size
            - complexity_score: Based on number of non-standard and dimensional items
    """
    result = {
        "section_name": section_name,
        "num_line_items": 0,
        "num_non_standard": 0,
        "num_with_axes": 0,
        "num_with_dimensions": 0,
        "top_concepts": [],
        "section_size": 0.0,
        "relative_size": 0.0,
        "complexity_score": 0.0
    }
    
    if section_facts.empty:
        return result
        
    # Basic line item count
    result["num_line_items"] = len(section_facts)
    
    # Non-standard concepts analysis
    non_standard = section_facts[~section_facts.concept_qname.str.startswith('us-gaap:', na=False)]
    result["num_non_standard"] = len(non_standard)
    
    # Dimensional usage
    result["num_with_axes"] = len(section_facts[section_facts.segment_axis.notna()])
    result["num_with_dimensions"] = len(section_facts[section_facts.has_dimensions == True])
    
    # Value analysis
    if 'value' in section_facts.columns:
        # Convert values to numeric where possible
        section_facts = section_facts.copy()  # Create a copy to avoid SettingWithCopyWarning
        section_facts.loc[:, 'abs_value'] = pd.to_numeric(section_facts['value'], errors='coerce').abs()
        
        # Calculate section size
        result["section_size"] = section_facts['abs_value'].sum()
        
        # Get top concepts by absolute value
        top_concepts = (section_facts
            .sort_values('abs_value', ascending=False)
            .head(5)
            [['concept_qname', 'label', 'value', 'abs_value']]
            .to_dict('records'))
        result["top_concepts"] = top_concepts
        
        # Calculate relative size if we have the full statement facts
        if fact_df is not None and not fact_df.empty:
            fact_df_copy = fact_df.copy()  # Create a copy to avoid SettingWithCopyWarning
            fact_df_copy.loc[:, 'abs_value'] = pd.to_numeric(fact_df_copy['value'], errors='coerce').abs()
            total_statement_size = fact_df_copy['abs_value'].sum()
            if total_statement_size > 0:
                result["relative_size"] = result["section_size"] / total_statement_size
    
    # Complexity score (simple heuristic)
    # Higher score for more non-standard and dimensional items
    base_complexity = 1.0
    non_standard_weight = result["num_non_standard"] / max(result["num_line_items"], 1)
    dimensional_weight = (result["num_with_axes"] + result["num_with_dimensions"]) / (2 * max(result["num_line_items"], 1))
    result["complexity_score"] = base_complexity + non_standard_weight + dimensional_weight
    
    return result
    

def find_concept_by_pattern_and_value(sop_df, *, account_types, exclude_patterns=None, top_k=1, 
                                      check_absolute_value=True, ascending=False,
                                      return_values=False, meta={}):
    """Find the top K concepts based on account type matching and value magnitude.
    
    Args:
        sop_df (pd.DataFrame): DataFrame containing SOP concepts and values
        account_types (list): List of account types to match (e.g., ['REV'], ['NI'])
        exclude_patterns (list, optional): Additional patterns to exclude
        top_k (int, optional): Number of top concepts to return. Defaults to 1.
        check_absolute_value (bool, optional): Whether to use absolute values for sorting. Defaults to True.
        ascending (bool, optional): Sort order for values. Defaults to False.
        return_values (bool, optional): Whether to return values along with concepts. Defaults to False.
        
    Returns:
        If top_k == 1 and not return_values:
            str: concept_qname of the matched concept with largest value
        If top_k > 1 or return_values:
            list: List of dicts containing concept info (qname, value, abs_value)
    """
    # Find matching concepts using identify_sop_section_for_concept
    sop_df = sop_df.copy()  # Create a copy to avoid SettingWithCopyWarning
    sop_df.loc[:, 'abs_value'] = pd.to_numeric(sop_df['value'], errors='coerce').abs()
    matching_concepts = []
    #unclassified_concepts = set()
    for idx, row in sop_df.iterrows():
        section, account_type, unclassified_concept = identify_sop_section_for_concept(
            str(row['concept_qname']), 
            str(row['label'])
        )
        if account_type in account_types:
            # Check additional exclude patterns if provided
            if exclude_patterns:
                exclude_str = '|'.join(exclude_patterns)
                if re.search(exclude_str, str(row['concept_name']), re.IGNORECASE):
                    continue
            matching_concepts.append(row)
        # if unclassified_concept:
        #     unclassified_concepts.append(unclassified_concept)
    if not matching_concepts:
        logger.debug(f"No matching concepts found for account_types with {str(account_types)} for {meta.get('cik', '')}/{meta.get('tfnm', '')}")
        return None if top_k == 1 and not return_values else []
    
    # Convert to DataFrame for easier processing
    matching_df = pd.DataFrame(matching_concepts)
    
    # Group by concept and get max value
    concept_max = matching_df.groupby("concept_qname").agg({
        'abs_value': 'max',
        'value': 'first'  # Take the first value for each concept
    })
    
    # Sort based on check_absolute_value parameter
    sort_column = 'abs_value' if check_absolute_value else 'value'
    concept_max = concept_max.sort_values(sort_column, ascending=ascending)
    
    if concept_max.empty:
        return None if top_k == 1 and not return_values else []
    
    # If only want top 1 concept and no values, return just the qname
    if top_k == 1 and not return_values:
        return concept_max.index.tolist()[0]
    
    # Otherwise return list of dicts with concept info
    if not return_values:
        return concept_max.index[:top_k].tolist()
    
    results = []
    for qname in concept_max.index[:top_k]:
        results.append({
            'concept_qname': qname,
            'value': concept_max.loc[qname, 'value'],
            'abs_value': concept_max.loc[qname, 'abs_value']
        })
    
    return results


def analyze_non_standard_concepts(stm_df, statement_type="SOP"):
    """Analyze concepts that don't use the us-gaap namespace."""
    non_standard_concepts = stm_df[
        ~stm_df.concept_qname.str.startswith('us-gaap:', na=False)
    ]
    return {
        f"num_non_standard_concepts_{statement_type.lower()}": len(non_standard_concepts)
    }

def analyze_dimensional_usage(fact_df, stm_df, statement_type="SOP"):
    """Analyze the usage of dimensions and axes in SOP facts."""
    sop_facts = fact_df[
        fact_df.concept_qname.isin(stm_df.concept_qname) &
        (fact_df.statement_type == statement_type) 
    ]
    
    facts_with_axes = sop_facts[sop_facts.segment_axis.notna()]
    facts_with_dimensions = sop_facts[sop_facts.has_dimensions == True]
    
    return {
        f"num_facts_with_axes_{statement_type.lower()}": len(facts_with_axes),
        f"num_facts_with_dimensions_{statement_type.lower()}": len(facts_with_dimensions)
    }

def identify_sop_section_for_concept(concept_qname, label, order=None, classified_sections=None, meta={}):
    """
    Identify the section and account type for a single concept in the Statement of Operations.
    
    Args:
        concept_name (str): Name of the concept (can be us-gaap or company-specific)
        label (str): Label of the concept
        order (float, optional): Order of the concept in the statement
        classified_sections (dict, optional): Dictionary of already classified sections with their order ranges
        
    Returns:
        tuple: (section, account_type) where:
            - section: Section identifier (REV_COGS_GP, OP_EXP_OP_INC, etc.)
            - account_type: Specific account type within the section (REV, COGS, GP, etc.)
    """
    # First try exact matches with US-GAAP concepts
    
    for account_type, concepts in StatementOfOperations.EXACT_MATCHES.items():
        if concept_qname in concepts:
            return StatementOfOperations.ACCOUNT_TYPE_TO_SECTION[account_type], account_type, None
    
    # Combine concept name and label for pattern matching
    # Remove us-gaap: prefix if present for better matching
    concept_text = concept_qname.split(':')[0] if concept_qname else ''
    text = f"{concept_text} {label}"
    
    # Try pattern matching
    for account_type, pattern_list in StatementOfOperations.PATTERNS.items():
        if StatementOfOperations.matches_pattern(text, pattern_list):
            return StatementOfOperations.ACCOUNT_TYPE_TO_SECTION[account_type], account_type, None
    
    # If no match but we have order information and classified sections
    if order is not None and classified_sections is not None:
        for section, (min_order, max_order) in classified_sections.items():
            if min_order <= order <= max_order:
                # Try to infer account type based on surrounding concepts
                return section, 'OTHER', None
    
    # If still no match, log for analysis
    #logger.warning(f"Unclassified concept: {concept_name} with label: {label} for {meta.get('cik', '')}/{meta.get('tfnm', '')}")
    return None, None, concept_qname



def get_current_fact_df(fact_df, min_fact_ratio=0.5, max_periods=8, num_current_periods=2):
    """Get facts from the most recent reporting periods.
    
    Args:
        fact_df (pd.DataFrame): DataFrame containing all facts
        min_fact_ratio (float): Minimum ratio relative to 75th percentile of facts per period
        max_periods (int): Maximum number of periods to consider
        num_current_periods (int): Number of most recent periods to return
        
    Returns:
        pd.DataFrame: Facts from the most recent periods
        
    Notes:
        This function may be moved to openesef.engines.py    
    """
    if fact_df.empty:
        logger.warning("Empty fact_df provided to get_current_fact_df")
        return fact_df.copy()
        
    if "period_string" not in fact_df.columns:
        logger.error("fact_df missing required column 'period_string'")
        return fact_df.copy()

    # Count facts per period
    context_counts = fact_df.groupby("period_string").size().sort_values(ascending=False).reset_index()
    
    # Filter periods with sufficient facts
    min_facts = context_counts[0].quantile(0.75) * min_fact_ratio
    context_counts = context_counts.loc[context_counts[0] >= min_facts]
    
    # Get most recent periods from top periods
    context_counts = context_counts.head(max_periods)
    context_counts.sort_values("period_string", inplace=True, ascending=True)
    current_contexts = context_counts.tail(num_current_periods).period_string.tolist()
    
    logger.debug(f"Selected {len(current_contexts)} current periods: {current_contexts}")
    
    return fact_df.loc[fact_df.period_string.isin(current_contexts)].copy()

def merge_statement_dataframe(link_df, current_fact_sop_df, statement_type="SOP", meta={}):
    """Extract Statement of Operations (SOP) dataframe by merging link and fact data.
    
    Args:
        link_df (pd.DataFrame): DataFrame containing presentation linkbase information
        current_fact_df (pd.DataFrame): DataFrame containing current period facts
        
    Returns:
        pd.DataFrame: Merged DataFrame containing SOP facts with presentation information
    
    Notes:
        This function may be moved to openesef.engines.py        
    """
    if link_df.empty or current_fact_sop_df.empty:
        logger.warning(f"Empty DataFrame provided to get_sop_dataframe for {meta.get('cik', '')}/{meta.get('tfnm', '')}")
        return pd.DataFrame()

    # Validate required columns
    required_link_cols = ["statement_type", "concept_qname", "segment_axis", "segment_axis_member"]
    required_fact_cols = ["concept_qname", "segment_axis", "segment_axis_member"]
    
    # missing_link_cols = [col for col in required_link_cols if col not in link_df.columns]
    # missing_fact_cols = [col for col in required_fact_cols if col not in current_fact_sop_df.columns]
    
    # if missing_link_cols or missing_fact_cols:
    #     logger.debug(f"Missing columns - link_df: {missing_link_cols}, fact_df: {missing_fact_cols} for {meta.get('cik', '')}/{meta.get('tfnm', '')}")
        #return pd.DataFrame()

    # Extract SOP concepts
    #statement_type="SOP"
    stm_df = link_df[link_df.statement_type == statement_type].copy()
    #stm_df.loc[stm_df.concept_qname == "us-gaap:EarningsPerShareBasic", ["concept_qname", "label", "statement_type", "order"]]# just one;
    #current_fact_sop_df.loc[current_fact_sop_df.concept_qname == "us-gaap:EarningsPerShareBasic", ["fact_index", "label", "statement_type","segment_dimension_member", "value"]]
    
    if stm_df.empty:
        logger.warning(f"No SOP concepts found in link_df for {meta.get('cik', '')}/{meta.get('tfnm', '')}") ### **MAJOR ISSUE**
        return pd.DataFrame()

    # Merge with facts
    pre_merge_count = len(stm_df)
    merge_cols = ["concept_qname"]
    
    # Only include segment columns in merge if they contain data
    if "segment_axis" in stm_df.columns and "segment_axis" in current_fact_sop_df.columns:
        if stm_df.segment_axis.notna().any() and current_fact_sop_df.segment_axis.notna().any():
            merge_cols.extend(["segment_axis", "segment_axis_member"])

    if "segment_dimension" in stm_df.columns and "segment_dimension" in current_fact_sop_df.columns:
        if stm_df.segment_axis.notna().any() and current_fact_sop_df.segment_axis.notna().any():
            merge_cols.extend(["segment_dimension", "segment_dimension_member"])

    
    stm_df_merged = stm_df.merge(
        current_fact_sop_df[ merge_cols + ["fact_index", "value"]],
        on=merge_cols,
        how="inner"
    )
    #stm_df_merged.sort_values(by="fact_index")[["fact_index", "label",  "value"]].head(60)
    
    post_merge_count = len(stm_df_merged)
    logger.info(f"SOP merge results: {pre_merge_count} concepts, {post_merge_count} facts after merge for {meta.get('cik', '')}/{meta.get('tfnm', '')}")
    
    return stm_df_merged




def get_child_concepts(reporter, network, concept, taxonomy, visited=None): # not used?
    """Recursively get all child concepts of a given concept
    not called by anyone else?"""
    if visited is None:
        visited = set()

    # Get concept identifier (name or qname)
    concept_id = str(concept.qname) if hasattr(concept, 'qname') else str(concept)

    # Avoid circular references
    if concept_id in visited:
        return []
    
    visited.add(concept_id)
    children = []

    # Get all members from the network
    members = network.get_members(start_concept=concept, include_head=False)
    
    # Process each member
    for member in members:
        member_id = str(member.Concept.qname) if hasattr(member.Concept, 'qname') else str(member.Concept)
        if member_id not in visited:
            child_info = {
                'name': member_id,
                'label': member.Concept.get_label() if hasattr(member.Concept, 'get_label') else 'N/A',
                'period_type': member.Concept.period_type if hasattr(member.Concept, 'period_type') else 'N/A',
                'balance': member.Concept.balance if hasattr(member.Concept, 'balance') else 'N/A',
                'level': member.Level if hasattr(member, 'Level') else 'N/A',
                'children': get_child_concepts(reporter, network, member.Concept, taxonomy, visited)
            }
            children.append(child_info)
    
    return children





def process_children(reporter, network, parent, concepts, grandparent_qname): #not used?
    """
    Recursively process children of a concept; 
    but is this function called by anyone else?
    """
    for child, rel in network.get_children(parent):
        # Get the order and preferred label from the relationship
        order = rel.order if hasattr(rel, 'order') else None
        preferred_label = rel.preferred_label if hasattr(rel, 'preferred_label') else None
        
        # Get the appropriate label based on preferred label role
        if preferred_label:
            label = reporter.get_label(child.qname, preferred_label)
        else:
            label = reporter.get_label(child.qname)
            
        child_dict = {
            "name": child.name,
            "qname": child.qname,
            "label": label,
            "order": order,
            "parent_qname": parent.qname,
            "grandparent_qname": grandparent_qname
        }
        concepts.append(child_dict)
        
        # Continue recursion
        process_children(reporter, network, child, concepts, parent.qname)


def build_concept_hierarchy(network, tax, reporter):
    """Build a dictionary mapping concepts to their list of parents"""
    concept_parents = {}
    concepts = get_network_details(tax, network, reporter)
    
    # First pass - build direct parent relationships
    direct_parents = {}
    for concept in concepts:
        qname = concept['qname']
        parent_qname = concept.get('parent_qname')
        if parent_qname:
            if qname not in direct_parents:
                direct_parents[qname] = set()
            direct_parents[qname].add(parent_qname)
    
    # Second pass - build full parent hierarchy
    def get_all_parents(qname, visited=None):
        if visited is None:
            visited = set()
        if qname in visited:
            return []
        visited.add(qname)
        
        parents = list(direct_parents.get(qname, set()))
        for parent in list(parents):  # Create a copy of parents list to iterate
            grandparents = get_all_parents(parent, visited)
            parents.extend(grandparents)
        return parents
    
    # Build full hierarchy for each concept
    for qname in direct_parents:
        concept_parents[qname] = get_all_parents(qname)
        
    return concept_parents

 


def tax_calc_df(tax):
    """
    Returns a dataframe of the calculation network
    """
    calc_arcs = []
    for k, v in tax.base_sets.items():
        if isinstance(k, tuple) and len(k) >= 1 and k[0] == 'calculationArc':
            calc_arcs.append((k, v))
        elif isinstance(k, str) and k.startswith('calculationArc'):
            # String key format: "arc_name|arcrole|role" → remap to tuple (arc_name, role, arcrole)
            parts = k.split('|', 2)
            if len(parts) == 3:
                calc_arcs.append(((parts[0], parts[2], parts[1]), v))
    #print(f"Found {len(calc_arcs)} calculation arcs")

    # for key in tax.base_sets:
    #     if key[0] == 'calculationArc':
    #         print(f"Found calculation arc with role: {key[1]}")

    # Check for calculation arcs in base_sets

    # Extract calculation relationships
    calc_records = []
    cycles_seen = set()  # qnames already reported as cyclic, to keep the log to one line each
    for key, link in calc_arcs:
        # key format: tuple (arc_name, role, arcrole) or string "arc_name|arcrole|role"
        if isinstance(key, (tuple, list)):
            role = key[1]
        elif '|' in str(key):
            parts = str(key).split('|')
            role = parts[2] if len(parts) >= 3 else str(key)
        else:
            role = str(key)
        role_name = role.split("/")[-1]

        if hasattr(link, 'relationships'):
            # Old-style XLink with relationships list
            for rel in link.relationships:
                record = {
                    'role': role,
                    'role_name': role_name,
                    'from_qname': str(rel['from'].qname),
                    'to_qname': str(rel['to'].qname),
                    'weight': rel['weight'],
                    'order': rel['order']
                }
                calc_records.append(record)
        elif hasattr(link, 'roots'):
            # BaseSet with roots/chain_dn tree
            from openesef.taxonomy.base_set import BaseSet
            bs_key = link.get_key()
            for root in link.roots:
                chain_dn = root.chain_dn.get(bs_key, [])
                for node in chain_dn:
                    record = {
                        'role': role,
                        'role_name': role_name,
                        'from_qname': str(root.qname),
                        'to_qname': str(node.Concept.qname),
                        'weight': float(node.Arc.weight) if hasattr(node.Arc, 'weight') else 1.0,
                        'order': float(node.Arc.order) if node.Arc.order is not None else None
                    }
                    calc_records.append(record)
                # Recurse into children.
                # _path is scoped to the current branch, not global: chain_dn is a DAG, so a
                # concept may legitimately sit under several parents and must emit a record
                # under each. Only a concept that is its own ANCESTOR is a cycle. This is the
                # same rule BaseSet.get_branch_members enforces with its `stack`.
                self_traverse = []
                def _traverse(parent_concept, bs_key, _path=None):
                    if _path is None:
                        _path = set()
                    parent_qname = str(parent_concept.qname)
                    if parent_qname in _path:
                        # XBRL 2.1 5.2.5.2 forbids directed cycles in calculation links, but
                        # filers ship them. The closing arc is already recorded; stop here.
                        if parent_qname not in cycles_seen:
                            cycles_seen.add(parent_qname)
                            logger.warning(
                                "Cyclic calculation relationship pruned at %s (role %s)",
                                parent_qname, role)
                        return
                    _path.add(parent_qname)
                    try:
                        children = parent_concept.chain_dn.get(bs_key, [])
                        for child_node in children:
                            rec = {
                                'role': role,
                                'role_name': role_name,
                                'from_qname': parent_qname,
                                'to_qname': str(child_node.Concept.qname),
                                'weight': float(child_node.Arc.weight) if hasattr(child_node.Arc, 'weight') else 1.0,
                                'order': float(child_node.Arc.order) if child_node.Arc.order is not None else None
                            }
                            self_traverse.append(rec)
                            _traverse(child_node.Concept, bs_key, _path)
                    finally:
                        _path.discard(parent_qname)  # pop on exit: this is what keeps _path branch-scoped
                for node in chain_dn:
                    _traverse(node.Concept, bs_key)
                calc_records.extend(self_traverse)

    calc_df = pd.DataFrame(calc_records)
    #print(calc_df)
    return calc_df


def is_numeric(x):
    try:
        float(x)
        return True
    except (ValueError, TypeError):
        return False


def process_statement_section(current_facts, statement_name):
    """
    Process facts for a specific statement section and add statement appearance info.
    
    Args:
        current_facts (pd.DataFrame): DataFrame containing current period facts
        statement_name (str): Name of the statement section to process
        
    Returns:
        pd.DataFrame: Processed facts for the statement section with added appearance info
    """
    section_facts = current_facts[current_facts.statement_name == statement_name].copy()
    
    if not section_facts.empty:
        section_facts['all_statements'] = section_facts['statement_appearances'].apply(lambda x: ', '.join(x))
        section_facts.sort_values('order', na_position='last', inplace=True)
        
    return section_facts

def analyze_statement_section(section_facts, fact_df, section_name="SOP"):
    """
    Analyze a specific section of a statement, providing metrics about its composition and complexity.
    
    Args:
        section_facts (pd.DataFrame): DataFrame containing facts for the specific section
        fact_df (pd.DataFrame): Complete fact DataFrame for additional context
        section_name (str): Name of the section being analyzed
        
    Returns:
        dict: Analysis results including:
            - num_line_items: Total number of line items in the section
            - num_non_standard: Number of non-standard (non-us-gaap) concepts
            - num_with_axes: Number of facts using axes
            - num_with_dimensions: Number of facts using dimensions
            - top_concepts: List of top 5 concepts by absolute value
            - section_size: Total absolute value of all facts in section
            - relative_size: Size relative to total statement size
            - complexity_score: Based on number of non-standard and dimensional items
    """
    result = {
        "section_name": section_name,
        "num_line_items": 0,
        "num_non_standard": 0,
        "num_with_axes": 0,
        "num_with_dimensions": 0,
        "top_concepts": [],
        "section_size": 0.0,
        "relative_size": 0.0,
        "complexity_score": 0.0
    }
    
    if section_facts.empty:
        return result
        
    # Basic line item count
    result["num_line_items"] = len(section_facts)
    
    # Non-standard concepts analysis
    non_standard = section_facts[~section_facts.concept_qname.str.startswith('us-gaap:', na=False)]
    result["num_non_standard"] = len(non_standard)
    
    # Dimensional usage
    result["num_with_axes"] = len(section_facts[section_facts.segment_axis.notna()])
    result["num_with_dimensions"] = len(section_facts[section_facts.has_dimensions == True])
    
    # Value analysis
    if 'value' in section_facts.columns:
        # Convert values to numeric where possible
        section_facts = section_facts.copy()  # Create a copy to avoid SettingWithCopyWarning
        section_facts.loc[:, 'abs_value'] = pd.to_numeric(section_facts['value'], errors='coerce').abs()
        
        # Calculate section size
        result["section_size"] = section_facts['abs_value'].sum()
        
        # Get top concepts by absolute value
        top_concepts = (section_facts
            .sort_values('abs_value', ascending=False)
            .head(5)
            [['concept_qname', 'label', 'value', 'abs_value']]
            .to_dict('records'))
        result["top_concepts"] = top_concepts
        
        # Calculate relative size if we have the full statement facts
        if fact_df is not None and not fact_df.empty:
            fact_df_copy = fact_df.copy()  # Create a copy to avoid SettingWithCopyWarning
            fact_df_copy.loc[:, 'abs_value'] = pd.to_numeric(fact_df_copy['value'], errors='coerce').abs()
            total_statement_size = fact_df_copy['abs_value'].sum()
            if total_statement_size > 0:
                result["relative_size"] = result["section_size"] / total_statement_size
    
    # Complexity score (simple heuristic)
    # Higher score for more non-standard and dimensional items
    base_complexity = 1.0
    non_standard_weight = result["num_non_standard"] / max(result["num_line_items"], 1)
    dimensional_weight = (result["num_with_axes"] + result["num_with_dimensions"]) / (2 * max(result["num_line_items"], 1))
    result["complexity_score"] = base_complexity + non_standard_weight + dimensional_weight
    
    return result

def ins_facts(xid, tax):
    """Extract facts from instance"""
    if xid is None or tax is None:
        logger.warning("xid or tax is None")
        return None
    if xid.xbrl is None:
        logger.warning("xid.xbrl is None")
        return None
    
    # Lazy import to avoid circular dependency - only import when needed
    #tax_pres = importlib.import_module('openesef.engines.tax_pres')
    t_pres = TaxonomyPresentation(tax)
    
    periods_dict = xid.identify_reporting_contexts()
    logger.info(f"Starting fact extraction with {len(xid.xbrl.facts)} facts and {len(periods_dict)} valid contexts")

    # Create a dictionary to store all statement appearances for each concept
    concept_statement_appearances = {}
    primary_statement_names = list()
    disclosure_names = list()
    
    # Before the fact_list loop, build concept hierarchies for each network
    network_hierarchies = {}
    pres_networks = TaxonomyPresentation.get_presentation_networks(tax)
    
    # First pass - record all statement appearances for each concept
    for network in pres_networks:
        statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
        network_hierarchies[statement_name] = build_concept_hierarchy(network, tax, t_pres.reporter)
        concepts = get_network_details(tax, network, t_pres.reporter)
        
        for i_concept, concept in enumerate(concepts):
            concept_qname = concept['qname']
            if concept_qname not in concept_statement_appearances:
                concept_statement_appearances[concept_qname] = []
            
            # Get the concept object to access its labels
            concept_obj = tax.concepts_by_qname.get(concept_qname)
            preferred_label = None
            if concept_obj and hasattr(concept_obj, 'labels'):
                terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
                if terse_role in concept_obj.labels:
                    preferred_label = concept_obj.get_label(role=terse_role, lang='en-US')
                if not preferred_label or preferred_label == 'N/A':
                    preferred_label = concept_obj.get_label(lang='en-US')
            
            statement_info = {
                'statement_name': statement_name,
                'statement_role': network.role if hasattr(network, 'role') else None,
                'is_primary_statement': t_pres._is_primary_statement(statement_name),
                'order': concept.get('order'),
                'order_presentation': i_concept,#concept.get('order'),
                'parent_qname': concept.get('parent_qname'),
                'label': preferred_label if preferred_label else concept.get('label')
            }
            if statement_info['is_primary_statement'] and not statement_info['statement_name'] in primary_statement_names:
                primary_statement_names.append(statement_name)
            else:
                disclosure_names.append(statement_name)
            concept_statement_appearances[concept_qname].append(statement_info)
    
    logger.info("Finished checking network with concepts")
    fact_list = []
    fact_list_disclosure = []
    
    # Process primary statements first
    for primary_statement_name in primary_statement_names:
        logger.debug(f"Processing facts for primary statement: {primary_statement_name}")
        added_concepts_for_this_statement = {}
        for key, fact in xid.xbrl.facts.items():
            concept = tax.concepts_by_qname.get(fact.qname)
            if not concept:
                continue
            
            concept_qname = str(concept.qname)
            statement_appearances = concept_statement_appearances.get(concept_qname, [])
            
            # Find the statement_info that matches the current primary_statement_name
            statement_info = None
            for app in statement_appearances:
                if app['statement_name'] == primary_statement_name and app['is_primary_statement']:
                    statement_info = app
                    #included_facts[key] = True
                    break
            
            if not statement_info:
                continue
            
            try:
                # Get the preferred label for display
                preferred_label = None
                if hasattr(concept, 'labels'):
                    # Try terse label first
                    terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
                    if terse_role in concept.labels:
                        preferred_label = concept.get_label(role=terse_role, lang='en-US')
                    # If no terse label, try standard label
                    if not preferred_label or preferred_label == 'N/A':
                        preferred_label = concept.get_label(lang='en-US')
                
                # Safely convert numeric values
                if fact.value is not None:
                    if fact.unit_ref is not None and "usd" in fact.unit_ref.lower() and fact.decimals == "-6":
                        raw_value = safe_numeric_conversion(fact.value)
                        value_mln = raw_value / 1000000 if raw_value is not None else None
                    else:
                        value_mln = None
                        
                    # For text storage, limit length and handle numeric values
                    if "text" in concept.name.lower():
                        stored_value = fact.value[:100]  # Truncate long text
                    else:
                        stored_value = safe_numeric_conversion(fact.value, default=str(fact.value))
                else:
                    stored_value = None
                    value_mln = None

                # Get segment data from context
                segment_data = {}
                segment_member_label = None
                ref_context = xid.xbrl.contexts.get(fact.context_ref)
                if ref_context and hasattr(ref_context, 'segment') and ref_context.segment:
                    #logger.debug(f"There are {len(ref_context.segment)} segments in the context")
                    items = list(ref_context.segment.items()) 
                    if items:
                        dimension, member = items[0]
                        member_value = member.text if hasattr(member, 'text') else str(member)
                        segment_data[str(dimension)] = member_value
                        
                        # Get the label for the segment member
                        member_qname = str(member_value)
                        member_concept = tax.concepts_by_qname.get(member_qname)
                        if member_concept and hasattr(member_concept, 'labels'):
                            terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
                            if terse_role in member_concept.labels:
                                segment_member_label = member_concept.get_label(role=terse_role, lang='en-US')
                            if not segment_member_label or segment_member_label == 'N/A':
                                segment_member_label = member_concept.get_label(lang='en-US')
                
                fact_dict = {
                    # Basic fact information
                    'fact_index': fact.fact_index,
                    'concept_name': concept.name,
                    'concept_qname': concept_qname,
                    "unit_ref": fact.unit_ref,
                    "decimals": fact.decimals,
                    'value': stored_value,
                    'value_mln': value_mln,
                    'context_ref': fact.context_ref,
                    
                    # Context information from periods_dict
                    'period_string': periods_dict.get(fact.context_ref, {}).get("period_string"),
                    'period_type': concept.period_type if hasattr(concept, 'period_type') else None,
                    'period_start': periods_dict.get(fact.context_ref, {}).get("period_start"),
                    'period_end': periods_dict.get(fact.context_ref, {}).get("period_end"),
                    'period_instant': periods_dict.get(fact.context_ref, {}).get("period_instant"),
                    'entity_scheme': periods_dict.get(fact.context_ref, {}).get("entity_scheme"),
                    'entity_identifier': periods_dict.get(fact.context_ref, {}).get("entity_identifier"),
                    
                    # Segment information as separate columns
                    'segment_axis': None,
                    'segment_axis_member': None,
                    'segment_dimension': None,
                    'segment_dimension_member': None,
                    'has_dimensions': False,
                    'dimension_count': 0,
                    
                    # Statement information from the selected appearance
                    'statement_name': statement_info['statement_name'],
                    'statement_role': statement_info['statement_role'],
                    'primary_statement': statement_info['is_primary_statement'],
                    'appears_in_statements': len(statement_appearances),
                    'statement_appearances': [app['statement_name'] for app in statement_appearances],
                    'statement_label': (f"{statement_info['statement_name']} "
                                    f"({statement_info['statement_role']})") if statement_info['statement_name'] else None,
                    'parent_qname': statement_info['parent_qname'],
                    'label': (f"{segment_member_label}" if segment_member_label else 
                             preferred_label if preferred_label else 
                             statement_info['label']),
                    'order_presentation': statement_info['order_presentation'],
                    'is_disclosure': False,
                    # Set fact_included based on primary statement status and segment validation
                    'fact_included': statement_info['is_primary_statement'] and t_pres._validate_segment(segment_data, statement_info['statement_name'])
                }

                # Get additional context information directly from the context object
                ref_context = xid.xbrl.contexts.get(fact.context_ref)
                if ref_context:
                    # Update period information
                    fact_dict['period'] = ref_context.get_period_string()
                    fact_dict['period_type'] = concept.period_type if hasattr(concept, 'period_type') else None
                    fact_dict['period_start'] = ref_context.period_start
                    fact_dict['period_end'] = ref_context.period_end
                    fact_dict['period_instant'] = ref_context.period_instant if hasattr(ref_context, 'period_instant') else None
                    
                    # Update entity information
                    fact_dict['entity_scheme'] = ref_context.entity_scheme if hasattr(ref_context, 'entity_scheme') else None
                    fact_dict['entity_identifier'] = ref_context.entity_identifier if hasattr(ref_context, 'entity_identifier') else None
                    
                    # Update segment information
                    if hasattr(ref_context, 'segment') and ref_context.segment:
                        items = list(ref_context.segment.items())
                        if items:
                            dimension, member = items[0]
                            member_value = member.text if hasattr(member, 'text') else str(member)
                            fact_dict['segment_axis'] = str(dimension)
                            fact_dict['segment_axis_member'] = member_value
                            fact_dict['segment_dimension'] = str(dimension)
                            fact_dict['segment_dimension_member'] = member_value
                    
                    # Update scenario information
                    if hasattr(ref_context, 'scenario') and ref_context.scenario:
                        scenario_info = {}
                        for dimension, member in ref_context.scenario.items():
                            scenario_info[str(dimension)] = member.text if hasattr(member, 'text') else str(member)
                        fact_dict['scenario'] = scenario_info
                    else:
                        fact_dict['scenario'] = None

                # Add concept parents
                statement_name = fact_dict['statement_name']
                concept_qname = fact_dict['concept_qname']
                fact_dict['concept_parents'] = network_hierarchies.get(statement_name, {}).get(concept_qname, [])

                fact_dict['fact_id'] = key

                this_fact_dict = {
                        "value": fact_dict['value'],    
                        #"statement_name": statement_name,
                        #"concept_qname": concept_qname,
                        "segment_axis": segment_data.get("segment_axis"), 
                        "segment_axis_member": segment_data.get("segment_axis_member"),
                        "segment_dimension": segment_data.get("segment_dimension"),
                        "segment_dimension_member": segment_data.get("segment_dimension_member")
                }
                # Create a unique key for this fact that includes all relevant dimensions
                fact_key = (
                    concept_qname,
                    fact_dict['value'],
                    fact_dict.get('segment_axis'),
                    fact_dict.get('segment_axis_member'),
                    fact_dict.get('period_string')
                )
                
                # Only add if we haven't seen this exact fact for this statement
                if statement_name in primary_statement_names and fact_key not in added_concepts_for_this_statement:
                    fact_list.append(fact_dict)
                    added_concepts_for_this_statement[fact_key] = True
                

            except Exception as e:
                logger.error(f"Error processing fact {key}: {str(e)}")
                continue
    logger.info(f"Finished extracting facts for primary statements with {len(fact_list)} facts")
    #mem_tops(top_n=10)            
    #check_memory_usage(threshold_gb=16)
    # Then process disclosures
    
    for key, fact in xid.xbrl.facts.items():
        # if included_facts.get(key, True):
        #     continue
        #for disclosure_name in tqdm(disclosure_names):
        #logger.debug(f"Processing facts for disclosure: {disclosure_name}")    
        #    for key, fact in xid.xbrl.facts.items():
        concept = tax.concepts_by_qname.get(fact.qname)
        if not concept:
            continue

        concept_qname = str(concept.qname)
        statement_appearances = concept_statement_appearances.get(concept_qname, [])
        
        # Find the statement_info that matches the current primary_statement_name
        statement_info = None
        for app in statement_appearances:
            if not app['is_primary_statement']:
                statement_info = app
                break

        if not statement_info:
            continue
        
        # concept_qname = str(concept.qname)
        # statement_appearances = concept_statement_appearances.get(concept_qname, [])
        
        # Find the statement_info that matches the current disclosure_name
        # statement_info = None
        # for app in statement_appearances:
        #     if app['statement_name'] == disclosure_name and not app['is_primary_statement']:
        #         statement_info = app
        #         break
        
        # if not statement_info:
        #     continue

        try:
            # Minimal fact dictionary with only essential information
            fact_dict = {
                'fact_index': fact.fact_index,
                'concept_name': concept.name,
                'concept_qname': concept_qname,
                'value': str(fact.value)[:100] if fact.value is not None else None,  # Truncate long values
                'context_ref': fact.context_ref,
                'statement_name': statement_info['statement_name'],
                'statement_role': statement_info['statement_role'],
                'primary_statement': False,  # These are disclosures
                'fact_id': key,
                'is_disclosure': True
            }
            
            # Add minimal context information if needed
            ref_context = xid.xbrl.contexts.get(fact.context_ref)
            if ref_context:
                fact_dict['period_string'] = periods_dict.get(fact.context_ref, {}).get("period_string")

            
            fact_list_disclosure.append(fact_dict)

        except Exception as e:
            logger.error(f"Error processing fact {key}: {str(e)}")
            continue
        
        except Exception as e:

            logger.error(f"Error processing fact {key}: {str(e)}")
            continue
    logger.info(f"Finished extracting facts for disclosures with {len(fact_list_disclosure)} facts")
    #mem_tops(top_n=30)            
    #check_memory_usage(threshold_gb=16)
    # Create DataFrames from collected facts
    fact_df = pd.DataFrame(fact_list)
    if "statement_name_norm"  in fact_df.columns:
        fact_df.loc[:, 'statement_name_norm'] = fact_df['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
    else:
        fact_df['statement_name_norm'] = fact_df['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)

    if "statement_type"  in fact_df.columns:
        fact_df.loc[:, 'statement_type'] = fact_df['statement_name'].map(t_pres.statement_types)
    else:
        fact_df['statement_type'] = fact_df['statement_name'].map(t_pres.statement_types)

    # Convert order to numeric and then to integer safely
    fact_df.loc[:, 'order_presentation'] = pd.to_numeric(fact_df['order_presentation'], errors='coerce')
    # Fill NaN with a large number to put them at the end
    
    # fact_df.loc[:, 'order'] = np.where(fact_df['order'].isna(), 
    #                            max_order + 100000 if pd.notna(max_order) else 99999,
    #                            fact_df['order'])
    #fact_df.loc[:, 'order'] = fact_df['order'].fillna(max_order + 100000 if pd.notna(max_order) else 99999)                           
    # Convert order to numeric and handle NaN values safely
    fact_df.loc[:, 'order_presentation'] = pd.to_numeric(fact_df['order_presentation'], errors='coerce')
    max_order = fact_df['order_presentation'].max()
    fill_value = max_order + 100000 if pd.notna(max_order) else 99999
    fact_df.loc[:,'order_presentation'] = np.where(fact_df['order_presentation'].isna(), fill_value, fact_df['order_presentation']).astype(int)
    
    
    fact_df = fact_df.sort_values(['statement_type', 'order_presentation']).copy()

    fact_df_disclosure = pd.DataFrame(fact_list_disclosure)
    if "statement_name_norm"  in fact_df_disclosure.columns:
        #fact_df_disclosure.loc[:, 'statement_name_norm'] = fact_df_disclosure['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
        raise ValueError("statement_name_norm already exists")
    else:
        fact_df_disclosure['statement_name_norm'] = fact_df_disclosure['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)

    if "statement_type"  in fact_df_disclosure.columns:
        #fact_df_disclosure.loc[:, 'statement_type'] = "Disclosure"
        raise ValueError("statement_type already exists")
    else:
        fact_df_disclosure['statement_type'] = "Disclosure"

    # Ensure numeric columns are properly typed
    numeric_columns = ['value_mln']
    for col in numeric_columns:
        if col in fact_df.columns:
            fact_df[col] = pd.to_numeric(fact_df[col], errors='coerce')
        if col in fact_df_disclosure.columns:
            fact_df_disclosure[col] = pd.to_numeric(fact_df_disclosure[col], errors='coerce')

    # Process calculations if available
    calc_df = tax_calc_df(tax)
    if not calc_df.empty:
        # Add statement name normalization to both DataFrames
        # This helps with matching since role_name and statement_name may have slight differences
        if "role_name_norm" not in calc_df.columns:
            calc_df['role_name_norm'] = calc_df['role_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
        else:
            raise ValueError("role_name_norm already exists")
        
        # Group calculation relationships by role and concept
        calc_by_role_parent = calc_df.groupby(['role_name_norm', 'from_qname'])[['to_qname', 'weight']].apply(
            lambda x: dict(zip(x['to_qname'], x['weight']))
        ).to_dict()
        
        calc_by_role_child = calc_df.groupby(['role_name_norm', 'to_qname'])[['from_qname', 'weight']].apply(
            lambda x: dict(zip(x['from_qname'], x['weight']))
        ).to_dict()
        
        # Function to get calculation children for a concept in a specific statement
        def get_calc_children_with_weights(row):
            key = (row['statement_name_norm'], row['concept_qname'])
            return calc_by_role_parent.get(key, {})
        
        # Function to get calculation parents for a concept in a specific statement
        def get_calc_parents_with_weights(row):
            key = (row['statement_name_norm'], row['concept_qname'])
            return calc_by_role_child.get(key, {})
        
        # Add calculation information to the facts DataFrame
        if "is_calc_parent" not in fact_df.columns:
            fact_df['is_calc_parent'] = fact_df.apply(
                lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_parent, 
                axis=1
            )
        else:
            raise ValueError("is_calc_parent already exists")

        if "is_calc_child" not in fact_df.columns:
            fact_df['is_calc_child'] = fact_df.apply(
                lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_child, 
                axis=1
            )
        else:
            raise ValueError("is_calc_child already exists")

        if "calc_children_with_weights" not in fact_df.columns:
            fact_df['calc_children_with_weights'] = fact_df.apply(get_calc_children_with_weights, axis=1)
        else:
            raise ValueError("calc_children_with_weights already exists")

        if "calc_parents_with_weights" not in fact_df.columns:
            fact_df['calc_parents_with_weights'] = fact_df.apply(get_calc_parents_with_weights, axis=1)
        else:
            raise ValueError("calc_parents_with_weights already exists")
        # Extract just the list of children and parents (without weights)
        if "calc_children" not in fact_df.columns:
            fact_df['calc_children'] = fact_df['calc_children_with_weights'].apply(lambda x: list(x.keys()))
        else:
            raise ValueError("calc_children already exists")

        if "calc_parents" not in fact_df.columns:
            fact_df['calc_parents'] = fact_df['calc_parents_with_weights'].apply(lambda x: list(x.keys()))
        else:
            raise ValueError("calc_parents already exists")
    # Update fact_included based on ID ranges for each primary statement
    fact_df = fact_df.sort_values(by='fact_index').copy()
    fact_df_disclosure = fact_df_disclosure.sort_values(by='fact_index').copy()

    if "is_disclosure" not in fact_df.columns:
        fact_df['is_disclosure'] = False
    else:
        fact_df.loc[:, 'is_disclosure'] = False

    if "is_disclosure" not in fact_df_disclosure.columns:
        fact_df_disclosure['is_disclosure'] = True
    else:
        fact_df_disclosure.loc[:, 'is_disclosure'] = True
    # Get concepts that only appear in statements or disclosures
    only_statement_concepts = [concept for concept in t_pres.statement_concepts if concept not in t_pres.disclosure_concepts]
    only_disclosure_concepts = [concept for concept in t_pres.disclosure_concepts if concept not in t_pres.statement_concepts]
    
    # Process each primary statement separately
    for primary_statement_name in primary_statement_names:
        # Get facts for this statement
        statement_facts = fact_df[fact_df['statement_name'] == primary_statement_name].copy()
        
        if statement_facts.empty:
            continue
            
        # Update fact_included based on both statement membership and segment validation
        # Create the mask
        mask = (fact_df['statement_name'] == primary_statement_name)

        # Calculate new values directly on the original DataFrame
        fact_df.loc[mask, 'fact_included'] = fact_df.loc[mask].apply(
            lambda row: (
                row['primary_statement'] and (
                    (pd.isna(row['segment_axis']) and pd.isna(row['segment_dimension'])) or
                    t_pres._validate_segment(
                        {
                            row['segment_axis']: row['segment_axis_member'] if pd.notna(row['segment_axis_member']) else None,
                            row['segment_dimension']: row['segment_dimension_member'] if pd.notna(row['segment_dimension_member']) else None
                        } if pd.notna(row['segment_axis']) or pd.notna(row['segment_dimension']) else {},
                        primary_statement_name
                    )
                )
            ),
            axis=1
        )        
        # Move non-validated dimensional facts to disclosures
        dimensional_mask = mask & (
            (fact_df['segment_axis'].notna() & ~fact_df['fact_included']) |
            (fact_df['segment_dimension'].notna() & ~fact_df['fact_included'])
        )
        #fact_df['statement_type'] = np.where(dimensional_mask, 'Disclosure', fact_df['statement_type'])
        #fact_df['is_disclosure'] = np.where(dimensional_mask, True, fact_df['is_disclosure'])
        #fact_df['fact_included'] = np.where(dimensional_mask, False, fact_df['fact_included'])
        fact_df.loc[dimensional_mask, 'statement_type'] = 'Disclosure'
        fact_df.loc[dimensional_mask, 'is_disclosure'] = True
        fact_df.loc[dimensional_mask, 'fact_included'] = False

    fact_df = pd.concat([fact_df, fact_df_disclosure])
    # Convert to boolean, treating NaN as False
    if not 'fact_included' in fact_df.columns:
        raise ValueError("fact_included not in fact_df")
    else:
        fact_df.loc[:,'fact_included'] = pd.to_numeric(fact_df['fact_included'], errors='coerce').fillna(0).astype(bool)
    #mem_tops(top_n=10)
    #mem_tops(top_n=100)            
    check_memory_usage(threshold_gb=16)

    
    # Update fact_included for this statement's facts


    
    for thisobj in [t_pres, xid, tax, periods_dict, fact_df_disclosure, fact_list_disclosure, fact_list, concept_statement_appearances, network_hierarchies, primary_statement_names, disclosure_names, only_statement_concepts, only_disclosure_concepts]:
        try:
            del thisobj
        except:
            pass
    try:
        gc.collect()
    except:
        pass
    logger.info("Fact extraction completed")
    return fact_df


# Add example usage function at the end of the file
# if __name__ == "__main__":
#     """Example of how to use the TaxonomyPresentation class with order information"""
#     from openesef.edgar.loader import load_xbrl_filing
#     # Load a filing
#     # filing_url = "https://www.sec.gov/Archives/edgar/data/1004980/0001004980-22-000009.txt"
#     # Process memory usage (20.1GB) exceeded threshold (8GB) for https://www.sec.gov/Archives/edgar/data/766704/0000766704-22-000013.txt
#     #xid, tax = load_xbrl_filing(filing_url="https://www.sec.gov/Archives/edgar/data/766704/0000766704-22-000013.txt", memory_threshold_gb=16)
#     #xid, tax = load_xbrl_filing(ticker="AAPL", year=2020)
#     filing_url = "https://www.sec.gov/Archives/edgar/data/1013871/0001013871-22-000010.txt"
#     #filing_url = "https://www.sec.gov/Archives/edgar/data/1172298/0001415889-15-002688.txt"
#     xid, tax = load_xbrl_filing(filing_url=filing_url, memory_threshold_gb=16)
#     fact_df = ins_facts(xid, tax)
#     fact_df.sort_values(by='fact_index', inplace=True)
#     fact_df["val_mln"] = fact_df["value"].apply(lambda x: float(x)/1000000 if is_numeric(x) and float(x) > 1000000 else x)
    
#     current_period_string = fact_df.period_string.value_counts().index[0]
#     current_facts = fact_df[fact_df.period_string == current_period_string].reset_index(drop=True)
    
#     t_pres = TaxonomyPresentation(tax)
#     link_df = t_pres.link_df
#     # Get facts for each major statement
#     so_facts = process_statement_section(current_facts, t_pres.name_sop)
#     fp_facts = process_statement_section(current_facts, t_pres.name_sfp)
#     cf_facts = process_statement_section(current_facts, t_pres.name_scf)
    
    
#     # Export Statement of Operations
#     if not so_facts.empty:
#         so_facts[["fact_index", "concept_qname","label", "value", "value_mln", "segment_axis", 
#                  "appears_in_statements", "all_statements", "order", "fact_included"]].to_excel("/tmp/apple_2020_so.xlsx")
        
        
#         #fact_df = fact_df.loc[fact_df.fact_included ]
#         current_period_string = fact_df.period_string.value_counts().index[0]
#         current_facts = fact_df[fact_df.period_string == current_period_string].reset_index(drop=True)

#         current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop) & (current_facts['fact_included']==True) , [ 'concept_qname',  ]]#.head(30)
#         current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop) & (current_facts['fact_included']==True) , [ 'label', "segment_axis","segment_axis_member", "value" ]]#.head(30)
#         current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop)].shape #45
#         t_pres.concept_df.loc[t_pres.concept_df.statement_name==t_pres.name_sop].shape #25
#         current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop)  , ].to_excel("/tmp/apple_2020_so_current.xlsx")
#         #print(f"\nStatement of Operations exported with {len(so_facts)} facts")
#         # Print concepts that appear in multiple statements
#         multi_statement_so = so_facts[so_facts.appears_in_statements > 1]
#         # if not multi_statement_so.empty:
#         #     print("Concepts appearing in multiple statements:")
#         #     print(multi_statement_so[["concept_name", "all_statements"]].drop_duplicates())

#         # Get calculation information for a specific statement
#         so_concepts = t_pres.link_df[t_pres.link_df.statement_name == t_pres.name_sop]

#         # View concepts that are calculation parents
#         calc_parents = so_concepts[so_concepts.is_calc_parent]
        
#         # View calculation relationships for a specific concept
#         concept_info = so_concepts[so_concepts.concept_name == 'NetIncomeLoss']
#         print("Children:", concept_info.calc_children.iloc[0])
#         print("Children weights:", concept_info.calc_children_weights_str.iloc[0])
#         print("Children weights:", concept_info.calc_children_weights_dict.iloc[0])
#         concept_info.to_dict()
    
#     # Export Balance Sheet (Financial Position)
#     if not fp_facts.empty:
#         fp_facts[["fact_index", "concept_name", "value", "value_mln", "segment_axis",
#                  "appears_in_statements", "all_statements", "order", "fact_included"]].to_excel("/tmp/apple_2020_bs.xlsx")
#         #print(f"\nBalance Sheet exported with {len(fp_facts)} facts")
#         # Print concepts that appear in multiple statements
#         multi_statement_fp = fp_facts[fp_facts.appears_in_statements > 1]
#         # if not multi_statement_fp.empty:
#         #     print("Concepts appearing in multiple statements:")
#         #     print(multi_statement_fp[["concept_name", "all_statements"]].drop_duplicates())
    
#     # Export Cash Flow Statement
#     if not cf_facts.empty:
#         cf_facts[["fact_index", "concept_name", "value", "value_mln", "segment_axis",
#                  "appears_in_statements", "all_statements", "order", "fact_included"]].to_excel("/tmp/apple_2020_cf.xlsx")
#         #print(f"\nCash Flow Statement exported with {len(cf_facts)} facts")
#         # Print concepts that appear in multiple statements
#         multi_statement_cf = cf_facts[cf_facts.appears_in_statements > 1]
#         # if not multi_statement_cf.empty:
#         #     print("Concepts appearing in multiple statements:")
#         #     print(multi_statement_cf[["concept_name", "all_statements"]].drop_duplicates())
    
#     # Summary statistics
#     logger.info("\n".join([
#         f"\nSummary Statistics:",
#         f"Total facts in current period: {len(current_facts)}",
#         f"Facts in Statement of Operations: {len(so_facts)}",
#         f"Facts in Balance Sheet: {len(fp_facts)}",
#         f"Facts in Cash Flow Statement: {len(cf_facts)}"
#     ]))
    
#     # Analyze each section of the statement
#     so_analysis = analyze_statement_section(so_facts, fact_df, "Statement of Operations")
#     fp_analysis = analyze_statement_section(fp_facts, fact_df, "Statement of Financial Position")
#     cf_analysis = analyze_statement_section(cf_facts, fact_df, "Statement of Cash Flows")
    
#     # Print analysis results
#     for analysis in [so_analysis, fp_analysis, cf_analysis]:
#         if analysis["num_line_items"] > 0:
#             print(f"\nAnalysis for {analysis['section_name']}:")
#             print(f"Line items: {analysis['num_line_items']}")
#             print(f"Non-standard concepts: {analysis['num_non_standard']}")
#             print(f"Dimensional usage: {analysis['num_with_dimensions']} items")
#             print(f"Relative size: {analysis['relative_size']:.2%}")
#             print(f"Complexity score: {analysis['complexity_score']:.2f}")
#             print("\nTop concepts by value:")
#             for concept in analysis["top_concepts"][:3]:  # Show top 3
#                 print(f"- {concept['concept_qname']}: {concept['value']}")
    
# if False:    
#     # # Continue with the other analysis examples...
#     #                 items = list(ref_context.segment.items()) 
#     #                 if items:
#     #                     dimension, member = items[0]
#     # Example 1: Show all appearances of NetIncomeLoss
#     ni_facts = current_facts[current_facts.concept_name == "NetIncomeLoss"].copy()
#     ni_facts['all_statements'] = ni_facts['statement_appearances'].apply(lambda x: ', '.join(x))
#     ni_facts[["fact_index", "concept_name", "value", "statement_name", "all_statements", 
#               "appears_in_statements", "fact_included"]].to_excel("/tmp/ni_all_statements.xlsx")
    
#     # Example 2: Show facts that appear in multiple statements
#     multi_statement_facts = current_facts[current_facts.appears_in_statements > 1].copy()
#     multi_statement_facts['all_statements'] = multi_statement_facts['statement_appearances'].apply(lambda x: ', '.join(x))
#     multi_statement_facts[["fact_index", "concept_name", "value", "statement_name", 
#                           "all_statements", "appears_in_statements", "fact_included"]].to_excel("/tmp/multi_statement_facts.xlsx")
    
#     # Example 3: Enhanced statement of operations export with statement appearance info
#     so_facts = current_facts[current_facts.statement_name == t_pres.name_sop].copy()
#     so_facts['all_statements'] = so_facts['statement_appearances'].apply(lambda x: ', '.join(x))
#     so_facts[["fact_index", "concept_name", "value", "segment_axis", "period_end", 
#               "fact_included", "appears_in_statements", "all_statements"]].to_excel("/tmp/apple_2020_so_enhanced.xlsx")
    
#     # Example 4: Detailed analysis of a specific concept
#     def analyze_concept(concept_name):
#         concept_facts = current_facts[current_facts.concept_name == concept_name].copy()
#         if not concept_facts.empty:
#             # Add all_statements column first
#             concept_facts['all_statements'] = concept_facts['statement_appearances'].apply(lambda x: ', '.join(x))
            
#             print(f"\nAnalysis of concept: {concept_name}")
#             print(f"Appears in {concept_facts.iloc[0].appears_in_statements} statements:")
#             print(f"Statements: {', '.join(concept_facts.iloc[0].statement_appearances)}")
#             print(f"Primary statement: {concept_facts.iloc[0].statement_name}")
#             print(f"Fact included: {concept_facts.iloc[0].fact_included}")
#             #print("\nValues across contexts:")
#             return concept_facts[["fact_index", "value", "period_string", "statement_name", 
#                                 "all_statements", "appears_in_statements", "fact_included"]]
#         return pd.DataFrame()
    
#     # Example usage of analyze_concept
#     # ni_analysis = analyze_concept("NetIncomeLoss")
#     # if not ni_analysis.empty:
#     #     print(ni_analysis)  # Print to console first
#     #     ni_analysis.to_excel("/tmp/ni_analysis.xlsx")
    
#     # Example 5: Summary of concepts by number of statement appearances
#     statement_appearance_summary = current_facts.groupby('concept_name').agg({
#         'appears_in_statements': 'first',
#         'statement_appearances': 'first'
#     }).reset_index()
    
#     statement_appearance_summary['all_statements'] = statement_appearance_summary['statement_appearances'].apply(lambda x: ', '.join(x))
#     statement_appearance_summary = statement_appearance_summary.sort_values('appears_in_statements', ascending=False)
#     statement_appearance_summary.to_excel("/tmp/statement_appearance_summary.xlsx")
    
#     print(current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop)  , ['fact_index', 'concept_name', 'label', "segment_axis", 'value', 'period_end', 'fact_included']].head(30))
