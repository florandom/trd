"""Explicit temporary laboratory for an operator's native MT5 terminal test."""

import json
import shutil
import sys
from pathlib import Path

from sqlalchemy import select

from backend.domain.bridge import json_bytes
from backend.infrastructure.domain_models import Position
from infra.scripts.mt5_acceptance import ROOT, native_lab


def main(output_dir: Path | None):
    if output_dir is None or not sys.stdin.isatty():
        print(
            "Usa mt5:lab --output-dir con una nuova cartella privata da un terminale interattivo."
        )
        return 1
    output_dir = output_dir.resolve()
    if output_dir.exists():
        print("La cartella deve essere nuova; i registri esistenti non vengono sostituiti.")
        return 1
    output_dir.mkdir(parents=True, mode=0o700)
    config_path = output_dir / "config.json"
    try:
        with native_lab() as (scenario, config, _temporary):
            shutil.copytree(ROOT / "apps/mt5", output_dir / "TRD")
            config_path.write_bytes(json_bytes(config))
            config_path.chmod(0o600)
            print(
                "Laboratorio temporaneo: conto sintetico. Credenziali esterne non richieste."
            )
            print(f"Origine locale da autorizzare in MT5: {config['origin']}")
            print("Copia TRD in MQL5/Experts e config.json in MQL5/Files/TRD-LAB.")
            print("Compila e collega TrdLocalBridge; ActivateLocalSimulation=true.")
            print("Lascia LocalCrashPoint vuoto.")
            while True:
                choice = input("1 apertura; 2 stop; 3 chiusura; 4 stato; 0 termina: ").strip()
                if choice == "0":
                    break
                if choice == "1":
                    scenario.emit_signal()
                    print("Segnale sintetico registrato; il bridge rivaluta il rischio.")
                    continue
                with scenario.operator.connect() as connection:
                    rows = (
                        connection.execute(select(Position).order_by(Position.opened_at))
                        .mappings()
                        .all()
                    )
                if choice == "4":
                    print(
                        json.dumps(
                            [
                                {
                                    "posizione": i + 1,
                                    "stato": row["status"],
                                    "volume": str(row["volume"]),
                                }
                                for i, row in enumerate(rows)
                            ],
                            ensure_ascii=False,
                        )
                    )
                elif choice in {"2", "3"}:
                    number = input("Numero posizione: ").strip()
                    if not number.isdigit() or not 1 <= int(number) <= len(rows):
                        print("Posizione non disponibile.")
                        continue
                    if input("Conferma la richiesta simulata scrivendo CONFERMO: ") != "CONFERMO":
                        continue
                    action = "MODIFY_STOPS" if choice == "2" else "CLOSE"
                    levels = (
                        {"stop_loss": "1.09700", "take_profit": "1.11000"} if choice == "2" else {}
                    )
                    try:
                        scenario.operator_request(action, rows[int(number) - 1]["id"], **levels)
                        print("Richiesta confermata; la registrazione non prova l’esecuzione.")
                    except Exception:
                        print("Richiesta respinta: aggiorna lo stato e rivedi la posizione.")
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"Laboratorio non completato ({type(error).__name__}).")
        return 1
    finally:
        config_path.unlink(missing_ok=True)
    return 0
