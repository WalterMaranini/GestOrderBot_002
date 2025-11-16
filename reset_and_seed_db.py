"""
reset_and_seed_db.py

Script per:
- cancellare il database SQLite (orders.db)
- ricreare lo schema
- caricare:
  * 10 clienti (CLI_001 ... CLI_010)
  * 30 articoli ortofrutticoli a KG
  * 1 prezzo generico per articolo (customer_id = NULL)
"""

import os

from db_models import (
    init_db,
    SessionLocal,
    Customer,
    Article,
    Price,
)


def get_db_file_path() -> str:
    """
    Restituisce il path del file SQLite.
    Assumiamo DATABASE_URL = 'sqlite:///./orders.db' in db_models.py.
    """
    # Se vuoi essere più robusto, puoi passare il path via env o costante.
    return "orders.db"


def reset_database() -> None:
    """Cancella il file SQLite (se esiste) e ricrea lo schema."""
    db_path = get_db_file_path()

    if os.path.exists(db_path):
        print(f"[*] Rimuovo database esistente: {db_path}")
        os.remove(db_path)
    else:
        print(f"[*] Nessun database esistente da rimuovere ({db_path})")

    print("[*] Creo nuovo schema (tabelle)...")
    init_db()
    print("[+] Schema creato.\n")


def seed_customers(session: SessionLocal) -> None:
    """Inserisce 10 clienti CLI_001 ... CLI_010."""
    print("[*] Inserisco clienti di esempio...")

    for i in range(1, 11):
        code = f"CLI{i:03d}"
        name = f"Cliente {i:03d}"

        existing = session.query(Customer).filter(Customer.code == code).first()
        if existing:
            print(f"  - Cliente {code} già presente, salto.")
            continue

        cust = Customer(
            code=code,
            name=name,
            address=f"Via Fittizia {i}",
            city="Torino",
            province="TO",
            country="IT",
        )
        session.add(cust)

    session.commit()
    print("[+] Clienti inseriti.\n")


def seed_articles_and_prices(session: SessionLocal) -> None:
    """
    Inserisce 30 articoli ortofrutta e per ciascuno un prezzo GENERICO
    (prezzo non specifico di cliente: customer_id = NULL).
    """

    print("[*] Inserisco articoli e prezzi generici...")

    articoli = [
        # code, description, unit, price (EUR/KG)
        ("mela",         "Mela Golden",                 "KG", 1.80),
        ("pera",         "Pera Williams",               "KG", 2.10),
        ("banana",       "Banana",                      "KG", 1.60),
        ("arancia",      "Arancia Navel",               "KG", 1.90),
        ("mandarino",    "Mandarino",                   "KG", 2.20),
        ("kiwi",         "Kiwi Verde",                  "KG", 2.50),
        ("ananas",       "Ananas",                      "KG", 2.80),
        ("fragola",      "Fragola",                     "KG", 4.50),
        ("pesca",        "Pesca Gialla",                "KG", 2.70),
        ("albicocca",    "Albicocca",                   "KG", 3.20),
        ("susina",       "Susina",                      "KG", 2.40),
        ("uva_bianca",   "Uva Bianca",                  "KG", 2.60),
        ("uva_nera",     "Uva Nera",                    "KG", 2.80),
        ("ciliegia",     "Ciliegia",                    "KG", 6.00),
        ("melone",       "Melone Retato",               "KG", 1.90),
        ("anguria",      "Anguria",                     "KG", 1.20),
        ("pomodoro",     "Pomodoro da Insalata",        "KG", 2.10),
        ("zucchina",     "Zucchina Chiara",             "KG", 1.80),
        ("melanzana",    "Melanzana",                   "KG", 1.90),
        ("peperone",     "Peperone Giallo/Rosso",       "KG", 2.40),
        ("cavolfiore",   "Cavolfiore",                  "KG", 1.70),
        ("cavolo",       "Cavolo Verza",                "KG", 1.60),
        ("insalata",     "Insalata Gentile",            "KG", 3.00),
        ("carota",       "Carota",                      "KG", 1.30),
        ("patata",       "Patata",                      "KG", 1.10),
        ("cipolla",      "Cipolla Dorata",              "KG", 1.20),
        ("aglio",        "Aglio",                       "KG", 4.00),
        ("sedano",       "Sedano",                      "KG", 2.00),
        ("finocchio",    "Finocchio",                   "KG", 2.10),
        ("broccolo",     "Broccolo",                    "KG", 2.30),
    ]

    for code, descr, unit, price_value in articoli:
        # Articolo
        art = session.query(Article).filter(Article.code == code).first()
        if not art:
            art = Article(code=code, description=descr, unit=unit)
            session.add(art)
            session.flush()  # per ottenere art.id
            print(f"  - Inserito articolo {code}")
        else:
            print(f"  - Articolo {code} già presente, uso quello esistente")

        # Prezzo generico (customer_id = NULL)
        existing_price = (
            session.query(Price)
            .filter(Price.customer_id.is_(None), Price.article_id == art.id)
            .first()
        )

        if existing_price:
            existing_price.price = price_value
            existing_price.currency = "EUR"
            print(f"    > Aggiornato prezzo generico per {code} a {price_value} EUR/KG")
        else:
            p = Price(
                customer_id=None,       # generico
                article_id=art.id,
                price=price_value,
                currency="EUR",
            )
            session.add(p)
            print(f"    > Inserito prezzo generico per {code}: {price_value} EUR/KG")

    session.commit()
    print("[+] Articoli e prezzi generici inseriti.\n")


def main():
    # 1) reset DB
    reset_database()

    # 2) crea sessione
    session = SessionLocal()
    try:
        # 3) seed clienti
        seed_customers(session)

        # 4) seed articoli + prezzi
        seed_articles_and_prices(session)

        print("[✓] Popolamento database completato.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
