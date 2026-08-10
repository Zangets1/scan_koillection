from app.importer import build_item_name, normalize_date
from app.lookup import clean_genres, merge, same_book
from app.models import AddRequest, BookMeta


def make(**kwargs) -> BookMeta:
    return BookMeta(**{"isbn13": "9782070368228", **kwargs})


def test_le_premier_fournisseur_gagne_champ_par_champ():
    bnf = make(title="1984", publisher="Gallimard", sources=["bnf"], authors=["George Orwell"])
    openlibrary = make(
        title="1984",
        publisher="Penguin",
        page_count=328,
        synopsis="Un roman dystopique.",
        sources=["openlibrary"],
    )
    merged = merge([bnf, openlibrary], "9782070368228")
    assert merged.publisher == "Gallimard"      # la BnF est prioritaire
    assert merged.page_count == 328             # complété par OpenLibrary
    assert merged.synopsis == "Un roman dystopique."
    assert merged.sources == ["bnf", "openlibrary"]


def test_une_notice_dun_autre_livre_est_ecartee():
    bnf = make(title="Un si fol espoir", authors=["Marie Dupont"], sources=["bnf"])
    autre = make(
        title="Bosanski jezik",
        authors=["Jasmin Hodžić"],
        synopsis="Texte sans rapport",
        sources=["openlibrary"],
    )
    merged = merge([bnf, autre], "9791234567896")
    assert merged.title == "Un si fol espoir"
    assert merged.synopsis is None
    assert merged.sources == ["bnf"]


def test_un_auteur_commun_suffit_a_rapprocher_deux_titres():
    assert same_book(
        make(title="1984", authors=["George Orwell"]),
        make(title="Nineteen Eighty-Four", authors=["George Orwell"]),
    )


def test_genres_nettoyes():
    assert clean_genres(["form:manga", "Bandes dessinées", "x", "Aventure"]) == [
        "Bandes dessinées",
        "Aventure",
    ]


def test_serie_deduite_du_titre_pendant_la_fusion():
    merged = merge([make(title="Naruto, Tome 4 : Le pont des héros")], "9782723489898")
    assert merged.series == "Naruto"
    assert merged.volume == 4
    assert merged.title == "Le pont des héros"


def test_candidats_de_couverture_toujours_completes_par_openlibrary():
    merged = merge([make(title="1984", cover_url="https://catalogue.bnf.fr/couverture?x")], "9782070368228")
    assert merged.cover_candidates == [
        "https://catalogue.bnf.fr/couverture?x",
        "https://covers.openlibrary.org/b/isbn/9782070368228-L.jpg",
    ]


def test_nom_ditem_avec_et_sans_serie():
    gabarit = "{series} - T{volume:02d} - {title}"
    avec = AddRequest(title="Le pont des héros", series="Naruto", volume=4)
    sans = AddRequest(title="1984")
    assert build_item_name(avec, gabarit) == "Naruto - T04 - Le pont des héros"
    assert build_item_name(sans, gabarit) == "1984"
    # Un tome inconnu ne doit pas produire « Naruto - T - … ».
    assert build_item_name(AddRequest(title="Tome hors série", series="Naruto"), gabarit) == "Tome hors série"


def test_normalisation_de_date():
    assert normalize_date("2013") == "2013"
    assert normalize_date("2013-05-14") == "2013-05-14"
    assert normalize_date("DL 2016") == "2016"
    assert normalize_date("cop. 1991") == "1991"


def test_la_serie_peut_venir_dune_source_secondaire():
    # Cas réel : la notice BnF de « Harry Potter et l'ordre du Phénix » ne porte
    # pas la série ; OpenLibrary la fournit sous la forme « Harry Potter #5 ».
    bnf = make(title="Harry Potter et l'ordre du Phénix", authors=["J.K. Rowling"], sources=["bnf"])
    ol = make(
        title="Harry Potter et l'ordre du Phénix",
        authors=["J.K. Rowling"],
        series="Harry Potter",
        volume=5,
        sources=["openlibrary"],
    )
    merged = merge([bnf, ol], "9782070643066")
    assert (merged.series, merged.volume) == ("Harry Potter", 5)
