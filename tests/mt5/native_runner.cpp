void NativeCase(const string &name) {
 if(name=="disconnected") native_connected=false;
 if(name=="reconnected") native_connected=true;
 if(name=="real") native_account_i[ACCOUNT_TRADE_MODE]=2;
 if(name=="contest") native_account_i[ACCOUNT_TRADE_MODE]=1;
 if(name=="account_changed") native_account_i[ACCOUNT_LOGIN]=8;
 if(name=="server_changed") native_account_s[ACCOUNT_SERVER]="OTHER";
 if(name=="history_failed") native_history_ok=false;
 if(name=="symbol_failed") native_symbol_ok=false;
 if(name=="missing_metadata") native_symbol_d.erase(SYMBOL_VOLUME_STEP);
 if(name=="missing_account") native_account_d.erase(ACCOUNT_EQUITY);
 if(name=="nan_equity") native_account_d[ACCOUNT_EQUITY]=std::numeric_limits<double>::quiet_NaN();
 if(name=="inf_contract") native_symbol_d[SYMBOL_TRADE_CONTRACT_SIZE]=std::numeric_limits<double>::infinity();
 if(name=="negative_step") native_symbol_d[SYMBOL_VOLUME_STEP]=-1;
 if(name=="tiny_point") native_symbol_d[SYMBOL_POINT]=0.00000000000000001;
 if(name=="stale_tick") native_tick_age=11;
 if(name=="future_tick") native_tick_age=-1;
 if(name=="missing_position") native_positions[0].doubles.erase(POSITION_SL);
 if(name=="missing_order") native_orders[0].integers.erase(ORDER_STATE);
 if(name=="missing_deal") native_deals[0].doubles.erase(DEAL_FEE);
 if(name=="position_race") native_position_race=true;
 if(name=="position_capacity") native_positions.resize(65,native_positions[0]);
 if(name=="order_capacity") native_orders.resize(65,native_orders[0]);
 if(name=="history_capacity") native_deals.resize(129,native_deals[0]);
 if(name=="permissions_on") host_algo_allowed=true;
 if(name=="magic_candidate") native_positions[0].integers[POSITION_MAGIC]=20261012;
 if(name=="negative_equity") native_account_d[ACCOUNT_EQUITY]=-10;
 if(name=="netting") native_account_i[ACCOUNT_MARGIN_MODE]=0;
 if(name=="unicode") native_account_s[ACCOUNT_CURRENCY]="EURO\xc3\xa8";
 if(name=="ticket_overflow") native_positions[0].ticket=18446744073709551615UL;
 if(name=="duplicate_position") native_positions.push_back(native_positions[0]);
 if(name=="duplicate_order") native_orders.push_back(native_orders[0]);
 if(name=="duplicate_deal") native_deals.push_back(native_deals[0]);
 if(name=="disk_failed") host_disk_failed=true;
 if(name=="record_capacity") {
  native_positions.resize(64,native_positions[0]);native_orders.resize(64,native_orders[0]);
  native_deals.resize(128,native_deals[0]);native_history_orders.resize(128,native_history_orders[0]);
  for(int i=0;i<64;i++) { native_positions[i].ticket=10000000000000001UL+i;native_orders[i].ticket=10000000000000100UL+i; }
  for(int i=0;i<128;i++) { native_deals[i].ticket=10000000000001000UL+i;native_history_orders[i].ticket=10000000000002000UL+i; }
 }
}
static bool native_send_ok=false,native_resolved=false;static uint native_send_retcode=0;static ulong native_resolved_ticket=0;
void NativeStats(int initialized=-1) {
 std::cout<<"{\"initialized\":"<<initialized<<",\"status\":"<<TrdQuote(trd_native_status)<<",\"fault\":"<<TrdQuote(trd_native_fault)
 <<",\"sequence\":"<<trd_native_sequence<<",\"hints\":"<<trd_native_hint_count<<",\"native_calls\":"<<native_calls
 <<",\"broker_calls\":"<<native_trade_calls<<",\"history_from\":"<<native_history_from<<",\"history_to\":"<<native_history_to
 <<",\"send_ok\":"<<(native_send_ok?"true":"false")<<",\"send_retcode\":"<<native_send_retcode
 <<",\"resolved\":"<<(native_resolved?"true":"false")<<",\"resolved_ticket\":"<<TrdQuote(IntegerToString((long)native_resolved_ticket))
 <<",\"snapshot\":"<<(trd_native_snapshot.empty()?"null":trd_native_snapshot)<<"}"<<std::endl;
}
int main(int argc,char **argv) {
 if(argc!=10) return 2;
 host_root=argv[1];ActivateNativeReadOnly=string(argv[2])=="1";host_tester=string(argv[3])=="1";
 NativeExpectedLogin=argv[4];NativeExpectedServer=argv[5];NativeSymbol=argv[6];NativeJournal=argv[7];NativeHistorySeconds=std::stoi(argv[8]);
 NativeFixture();NativeCase(argv[9]);NativeStats(OnInit());string line;
 while(std::getline(std::cin,line)) {
  if(line=="STOP") break;
  if(line=="TICK") OnTimer();
  else if(line.rfind("SEND",0)==0) {
   MqlTradeRequest request={};MqlTradeResult result={};
   request.action=line=="SEND STOPS"?TRADE_ACTION_SLTP:TRADE_ACTION_DEAL;request.symbol=native_symbol;
   request.type=ORDER_TYPE_BUY;request.volume=0.08;request.price=1.1;request.sl=1.095;request.tp=1.11;request.magic=20261012;
   request.type_filling=ORDER_FILLING_FOK;
   if(line=="SEND CLOSE"||line=="SEND STOPS") request.position=10000000000000001UL;
   if(line=="SEND CLOSE") { request.type=ORDER_TYPE_SELL;request.price=1.0999;request.sl=0;request.tp=0; }
   if(line=="SEND STOPS") { request.volume=0;request.price=0; }
   native_send_ok=TrdNativeSend(request,result);native_send_retcode=result.retcode;
  }
  else if(line.rfind("RESOLVE ",0)==0) native_resolved=TrdNativeResolvePosition(line.substr(8),native_resolved_ticket);
  else if(line.rfind("CASE ",0)==0) NativeCase(line.substr(5));
  else if(line.rfind("HINT ",0)==0) {
   MqlTradeTransaction transaction={};MqlTradeRequest request={};MqlTradeResult result={};
   transaction.type=line.substr(5)=="request"?TRADE_TRANSACTION_REQUEST:TRADE_TRANSACTION_DEAL_ADD;
   transaction.symbol=native_symbol;transaction.deal=10000000000000005UL;transaction.order=10000000000000004UL;
   transaction.position=10000000000000001UL;transaction.volume=0.08;transaction.price=1.1;
   result.retcode=10009;result.request_id=99;result.retcode_external=-7;
   OnTradeTransaction(transaction,request,result);
  } else return 3;
  NativeStats();
 }
 OnDeinit(0);return 0;
}
