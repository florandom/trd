#property strict
#property version "0.10"
#property description "TRD collegamento nativo locale di sola lettura; invio broker escluso"
input bool ActivateNativeReadOnly=false;
input string NativeExpectedLogin="";
input string NativeExpectedServer="";
input string NativeSymbol="";
input string NativeJournal="";
input int NativeHistorySeconds=3600;

#include "../Include/TrdNative.mqh"

void TrdNativeDisplay()
{
   if(trd_native_snapshot==""||trd_native_fault!="")
      Comment("TRD sola lettura locale. Dati non disponibili. Invio broker disabilitato. Osservazioni: ",trd_native_sequence);
   else
      Comment("TRD sola lettura locale. Invio broker disabilitato. Ora UTC: "+TrdNativeStamp((long)TimeGMT())+" | Osservazioni: ",trd_native_sequence);
}

int OnInit()
{
   if(!ActivateNativeReadOnly) return INIT_SUCCEEDED;
   long login;
   if(MQLInfoInteger(MQL_TESTER)||!TrdSelfTest()||!TrdUnsigned(NativeExpectedLogin,login)||login<1||
      !TrdNativeText(NativeExpectedServer)||!TrdNativeText(NativeSymbol)||!TrdUuidValid(NativeJournal)||
      NativeHistorySeconds<60||NativeHistorySeconds>86400)
   { TrdNativeFail("NATIVE_LOCAL_INPUT_INVALID",true);return INIT_FAILED; }
   if(!TrdNativeIdentity()||!TrdNativeJournal()) return INIT_FAILED;
   if(!EventSetTimer(2)) { TrdNativeFail("NATIVE_TIMER_FAILED",true);return INIT_FAILED; }
   trd_native_status="NATIVE_READONLY_WAITING";TrdNativeDisplay();return INIT_SUCCEEDED;
}
void OnTimer()
{
   if(!ActivateNativeReadOnly) return;
   if(trd_native_fault!="") { TrdNativeDisplay();return; }
   string snapshot;
   if(!TrdNativeCapture(snapshot)) { TrdNativeDisplay();return; }
   string hints=TrdNativeHints();
   if(hints=="") { TrdNativeFail("NATIVE_TRANSACTION_INVALID",true);TrdNativeDisplay();return; }
   string record="{\"type\":\"OBSERVATION\",\"sequence\":"+TrdQuote(IntegerToString(trd_native_sequence+1))+
      ",\"snapshot\":"+snapshot+",\"transactions\":"+hints+"}";
   TrdJson verify;if(!verify.Parse(record)) { TrdNativeFail("NATIVE_RECORD_CAPACITY",true);TrdNativeDisplay();return; }
   if(!TrdNativeRecord(record)) { TrdNativeDisplay();return; }
   trd_native_sequence++;trd_native_hint_count=0;trd_native_snapshot=snapshot;
   trd_native_status="NATIVE_READONLY_OBSERVED";
   TrdNativeDisplay();
}
void OnTradeTransaction(const MqlTradeTransaction &transaction,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   // Bounded memory copy only. Native account/history reads and disk IO run on timer.
   TrdNativeBuffer(transaction,result);
}
void OnDeinit(const int reason)
{
   EventKillTimer();if(trd_native_file!=INVALID_HANDLE) FileClose(trd_native_file);
}
