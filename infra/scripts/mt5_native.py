"""Native observer source preparation and credential-free portable acceptance."""

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from infra.scripts.mt5_lab import ROOT, compile_native
from tests.mt5.native_helpers import NativeMqlProcess


def prepare(output_dir: Path | None):
    if output_dir is None:
        raise ValueError("Provide a new private --output-dir")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    try:
        for directory in ("Experts", "Include"):
            (output_dir / "TRD" / directory).mkdir(parents=True)
        for relative in (
            "Experts/TrdNativeReadOnly.mq5",
            "Include/TrdNative.mqh",
            "Include/TrdCore.mqh",
        ):
            shutil.copyfile(ROOT / "apps/mt5" / relative, output_dir / "TRD" / relative)
        source = output_dir / "TRD/Experts/TrdNativeReadOnly.mq5"
        text = source.read_text(encoding="utf-8")
        if text.count('input string NativeJournal="";') != 1:
            raise RuntimeError("Native source journal input changed")
        text = text.replace(
            'input string NativeJournal="";', f'input string NativeJournal="{uuid4()}";'
        )
        source.write_text(text, encoding="utf-8")
        (output_dir / "LEGGIMI.txt").write_text(
            "TRD collegamento nativo locale di sola lettura\n\n"
            "Compila TRD/Experts/TrdNativeReadOnly.mq5 con MetaEditor e conserva gli Include.\n"
            "Il sorgente non contiene chiamate per inviare ordini o richieste HTTP.\n"
            "Nei test finali accedi al conto DEMO solo nel terminale MT5.\n"
            "Imposta NativeExpectedLogin, NativeExpectedServer e NativeSymbol esatti.\n"
            "NativeJournal è già predisposto; conserva lo stesso valore nei riavvii.\n"
            "ActivateNativeReadOnly=false resta il default; abilita la lettura esplicitamente.\n"
            "NativeHistorySeconds=3600: un'ora in tempo broker; non attesta tutto lo storico.\n"
            "Osservazioni in Common/Files/TRD-NATIVE, con lock e registro persistente.\n"
            "Proteggi cartella e registri con permessi per il solo operatore; non condividerli.\n"
            "Non occorrono chiavi bridge, URL, WebRequest, provider API o database.\n"
            "Conti REAL/CONTEST e cambi di identità sono rifiutati.\n"
            "Lettura e transazioni non autorizzano ordini, né diventano dati paper.\n"
            "Compilazione nativa, terminale Windows e collaudo demo restano da verificare.\n",
            encoding="utf-8",
        )
    except BaseException:
        shutil.rmtree(output_dir)
        raise
    print("Sorgenti nativi predisposti in cartella privata. Lettura spenta; invio broker escluso.")
    return 0


def run_acceptance():
    with TemporaryDirectory(prefix="trd-mt5-native-") as temporary:
        root = Path(temporary)
        binary = compile_native(root / "build")
        with NativeMqlProcess(
            binary, root / "disabled", active=False, login="", server="", symbol=""
        ) as host:
            assert host.command("TICK")["native_calls"] == 0
        journal = uuid4()
        with NativeMqlProcess(
            binary, root / "terminal", journal=journal, case="permissions_on"
        ) as host:
            assert host.initial["initialized"] == 0
            host.command("HINT request")
            host.command("HINT deal")
            observed = host.command("TICK")
            data = observed["snapshot"]
            assert data["scope"] == "native-readonly" and not data["execution_authority"]
            assert data["account"]["trade_permission_observed"]
            assert len(data["positions"]) == len(data["orders"]) == 1
            assert len(data["deals"]) == 2 and len(data["history_orders"]) == 1
            target = host.command("RESOLVE 10000000000000002")
            assert target["resolved_ticket"] == "10000000000000001"
            for action in ("SEND", "SEND CLOSE", "SEND STOPS"):
                assert host.command(action)["status"] == "BROKER_SEND_DISABLED"
            assert host.command("TICK")["broker_calls"] == 0
        with NativeMqlProcess(binary, root / "terminal", journal=journal) as host:
            assert host.initial["sequence"] == 2 and host.initial["snapshot"] is None
            assert host.command("TICK")["sequence"] == 3
        return {
            "scope": "native-readonly",
            "runtime": "MQL5 source with native API fixtures",
            "terminal_observation_cycles": 3,
            "transaction_hints_buffered": 2,
            "all_account_positions_observed": 1,
            "pending_orders_observed": 1,
            "history_deals_observed": 2,
            "history_orders_observed": 1,
            "current_ticket_resolved": True,
            "restart_sequence_preserved": True,
            "send_gate_bypasses": 0,
            "broker_calls": 0,
            "external_connections": False,
            "native_metaeditor_terminal_acceptance": "still required",
            "operator_credentials_used": False,
        }


def accept():
    print(json.dumps(run_acceptance(), ensure_ascii=False, indent=2))
    return 0
