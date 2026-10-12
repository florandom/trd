// Native API fixtures only. Observation, validation and lifecycle stay in MQL source.
#include <cmath>
#include <sstream>
#include <iomanip>
#include <limits>
constexpr int TERMINAL_CONNECTED=100,TERMINAL_TRADE_ALLOWED=101;
constexpr int ACCOUNT_LOGIN=110,ACCOUNT_TRADE_MODE=111,ACCOUNT_MARGIN_MODE=112,ACCOUNT_TRADE_ALLOWED=113,ACCOUNT_TRADE_EXPERT=114;
constexpr int ACCOUNT_SERVER=120,ACCOUNT_CURRENCY=121,ACCOUNT_BALANCE=130,ACCOUNT_EQUITY=131,ACCOUNT_MARGIN_FREE=132,ACCOUNT_TRADE_MODE_DEMO=0;
constexpr int SYMBOL_POINT=140,SYMBOL_TRADE_TICK_SIZE=141,SYMBOL_VOLUME_MIN=142,SYMBOL_VOLUME_STEP=143,SYMBOL_VOLUME_MAX=144,SYMBOL_TRADE_CONTRACT_SIZE=145;
constexpr int SYMBOL_DIGITS=150,SYMBOL_TRADE_STOPS_LEVEL=151,SYMBOL_TRADE_FREEZE_LEVEL=152,SYMBOL_FILLING_MODE=153,SYMBOL_TRADE_MODE=154,SYMBOL_TRADE_CALC_MODE=155;
constexpr int SYMBOL_CURRENCY_BASE=160,SYMBOL_CURRENCY_PROFIT=161,SYMBOL_CURRENCY_MARGIN=162;
constexpr int POSITION_IDENTIFIER=170,POSITION_MAGIC=171,POSITION_TYPE=172,POSITION_SYMBOL=180,POSITION_VOLUME=190,POSITION_PRICE_OPEN=191,POSITION_SL=192,POSITION_TP=193;
constexpr int POSITION_TYPE_BUY=0,POSITION_TYPE_SELL=1;
constexpr int ORDER_POSITION_ID=200,ORDER_MAGIC=201,ORDER_TYPE=202,ORDER_STATE=203,ORDER_SYMBOL=210,ORDER_VOLUME_INITIAL=220,ORDER_VOLUME_CURRENT=221,ORDER_PRICE_OPEN=222,ORDER_SL=223,ORDER_TP=224;
constexpr int DEAL_ORDER=230,DEAL_POSITION_ID=231,DEAL_MAGIC=232,DEAL_TYPE=233,DEAL_ENTRY=234,DEAL_TIME_MSC=235,DEAL_SYMBOL=240,DEAL_VOLUME=250,DEAL_PRICE=251,DEAL_PROFIT=252,DEAL_COMMISSION=253,DEAL_SWAP=254,DEAL_FEE=255;
constexpr int TRADE_TRANSACTION_REQUEST=10,TRADE_TRANSACTION_DEAL_ADD=6;
constexpr uint TRADE_RETCODE_CLIENT_DISABLES_AT=10027;
struct MqlTick { datetime time=0;long time_msc=0;double bid=1.0999,ask=1.1; };
struct NativeRow { ulong ticket=0;std::map<int,long> integers;std::map<int,double> doubles;std::map<int,string> strings; };
static long native_calls=0,native_trade_calls=0,native_server_offset=7200,native_tick_age=0,native_position_selection=0;
static bool native_connected=true,native_history_ok=true,native_symbol_ok=true,native_position_race=false,native_timer_ok=true;
static string native_symbol="EURUSD.native";
static std::map<int,long> native_account_i={{ACCOUNT_LOGIN,7},{ACCOUNT_TRADE_MODE,ACCOUNT_TRADE_MODE_DEMO},{ACCOUNT_MARGIN_MODE,2},{ACCOUNT_TRADE_ALLOWED,1},{ACCOUNT_TRADE_EXPERT,1}};
static std::map<int,string> native_account_s={{ACCOUNT_SERVER,"TRD-NATIVE-FIXTURE"},{ACCOUNT_CURRENCY,"USD"}};
static std::map<int,double> native_account_d={{ACCOUNT_BALANCE,10250},{ACCOUNT_EQUITY,10249.5},{ACCOUNT_MARGIN_FREE,9999.5}};
static std::map<int,long> native_symbol_i={{SYMBOL_DIGITS,5},{SYMBOL_TRADE_STOPS_LEVEL,10},{SYMBOL_TRADE_FREEZE_LEVEL,5},{SYMBOL_FILLING_MODE,1},{SYMBOL_TRADE_MODE,4},{SYMBOL_TRADE_CALC_MODE,0}};
static std::map<int,double> native_symbol_d={{SYMBOL_POINT,0.00001},{SYMBOL_TRADE_TICK_SIZE,0.00001},{SYMBOL_VOLUME_MIN,0.01},{SYMBOL_VOLUME_STEP,0.01},{SYMBOL_VOLUME_MAX,100},{SYMBOL_TRADE_CONTRACT_SIZE,100000}};
static std::map<int,string> native_symbol_s={{SYMBOL_CURRENCY_BASE,"EUR"},{SYMBOL_CURRENCY_PROFIT,"USD"},{SYMBOL_CURRENCY_MARGIN,"EUR"}};
static std::vector<NativeRow> native_positions,native_orders,native_deals,native_history_orders;
static NativeRow *native_selected_position=nullptr,*native_selected_order=nullptr;
static long native_history_from=0,native_history_to=0;
bool MathIsValidNumber(double v) { return std::isfinite(v); }
double MathAbs(double v) { return std::abs(v); }
string DoubleToString(double v,int digits) { std::ostringstream s;s<<std::fixed<<std::setprecision(digits)<<v;return s.str(); }
ulong GetTickCount64() { return static_cast<ulong>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count()); }
datetime TimeTradeServer() { native_calls++;return TimeGMT()+native_server_offset; }
datetime TimeCurrent() { native_calls++;return TimeGMT()+native_server_offset; }
long TerminalInfoInteger(int property) { native_calls++;return property==TERMINAL_CONNECTED?native_connected:host_algo_allowed; }
long AccountInfoInteger(int property) { native_calls++;if(!native_account_i.count(property)) host_error=1;return native_account_i[property]; }
string AccountInfoString(int property) { native_calls++;if(!native_account_s.count(property)) host_error=1;return native_account_s[property]; }
double AccountInfoDouble(int property) { native_calls++;if(!native_account_d.count(property)) host_error=1;return native_account_d[property]; }
bool SymbolInfoTick(const string &symbol,MqlTick &tick) { native_calls++;if(symbol!=native_symbol||!native_symbol_ok) return false;tick.time=TimeGMT()+native_server_offset-native_tick_age;tick.time_msc=tick.time*1000;return true; }
template<class T> bool NativeGet(std::map<int,T> &values,int property,T &out) { native_calls++;auto found=values.find(property);if(found==values.end()) return false;out=found->second;return true; }
bool SymbolInfoDouble(const string &s,int p,double &v) { return s==native_symbol&&NativeGet(native_symbol_d,p,v); }
bool SymbolInfoInteger(const string &s,int p,long &v) { return s==native_symbol&&NativeGet(native_symbol_i,p,v); }
bool SymbolInfoString(const string &s,int p,string &v) { return s==native_symbol&&NativeGet(native_symbol_s,p,v); }
NativeRow* NativeFind(std::vector<NativeRow> &rows,ulong ticket) { for(auto &row:rows) if(row.ticket==ticket) return &row;return nullptr; }
int PositionsTotal() { native_calls++;return static_cast<int>(native_positions.size()); }
ulong PositionGetTicket(int i) { native_calls++;return i<static_cast<int>(native_positions.size())?native_positions[i].ticket:0; }
bool PositionSelectByTicket(ulong t) { native_calls++;native_selected_position=NativeFind(native_positions,t);native_position_selection++;if(native_position_race&&native_position_selection>static_cast<long>(native_positions.size())) native_selected_position->doubles[POSITION_PRICE_OPEN]+=0.01;return native_selected_position!=nullptr; }
bool PositionGetInteger(int p,long &v) { return native_selected_position&&NativeGet(native_selected_position->integers,p,v); }
bool PositionGetDouble(int p,double &v) { return native_selected_position&&NativeGet(native_selected_position->doubles,p,v); }
bool PositionGetString(int p,string &v) { return native_selected_position&&NativeGet(native_selected_position->strings,p,v); }
int OrdersTotal() { native_calls++;return static_cast<int>(native_orders.size()); }
ulong OrderGetTicket(int i) { native_calls++;return i<static_cast<int>(native_orders.size())?native_orders[i].ticket:0; }
bool OrderSelect(ulong t) { native_calls++;native_selected_order=NativeFind(native_orders,t);return native_selected_order!=nullptr; }
bool OrderGetInteger(int p,long &v) { return native_selected_order&&NativeGet(native_selected_order->integers,p,v); }
bool OrderGetDouble(int p,double &v) { return native_selected_order&&NativeGet(native_selected_order->doubles,p,v); }
bool OrderGetString(int p,string &v) { return native_selected_order&&NativeGet(native_selected_order->strings,p,v); }
bool HistorySelect(datetime from,datetime to) { native_calls++;native_history_from=from;native_history_to=to;return native_history_ok; }
int HistoryDealsTotal() { native_calls++;return static_cast<int>(native_deals.size()); }
int HistoryOrdersTotal() { native_calls++;return static_cast<int>(native_history_orders.size()); }
ulong HistoryDealGetTicket(int i) { native_calls++;return i<static_cast<int>(native_deals.size())?native_deals[i].ticket:0; }
ulong HistoryOrderGetTicket(int i) { native_calls++;return i<static_cast<int>(native_history_orders.size())?native_history_orders[i].ticket:0; }
bool HistoryDealGetInteger(ulong t,int p,long &v) { auto r=NativeFind(native_deals,t);return r&&NativeGet(r->integers,p,v); }
bool HistoryDealGetDouble(ulong t,int p,double &v) { auto r=NativeFind(native_deals,t);return r&&NativeGet(r->doubles,p,v); }
bool HistoryDealGetString(ulong t,int p,string &v) { auto r=NativeFind(native_deals,t);return r&&NativeGet(r->strings,p,v); }
bool HistoryOrderGetInteger(ulong t,int p,long &v) { auto r=NativeFind(native_history_orders,t);return r&&NativeGet(r->integers,p,v); }
bool HistoryOrderGetDouble(ulong t,int p,double &v) { auto r=NativeFind(native_history_orders,t);return r&&NativeGet(r->doubles,p,v); }
bool HistoryOrderGetString(ulong t,int p,string &v) { auto r=NativeFind(native_history_orders,t);return r&&NativeGet(r->strings,p,v); }
void Comment(const string &,long) {}
bool OrderSend(const MqlTradeRequest &,MqlTradeResult &) { native_trade_calls++;return false; }
bool OrderSendAsync(const MqlTradeRequest &,MqlTradeResult &) { native_trade_calls++;return false; }
bool OrderCheck(const MqlTradeRequest &,MqlTradeCheckResult &) { native_trade_calls++;return false; }
void NativeFixture() {
 NativeRow p;p.ticket=10000000000000001UL;p.integers={{POSITION_IDENTIFIER,10000000000000002},{POSITION_MAGIC,0},{POSITION_TYPE,POSITION_TYPE_BUY}};
 p.doubles={{POSITION_VOLUME,0.08},{POSITION_PRICE_OPEN,1.1},{POSITION_SL,0},{POSITION_TP,0}};p.strings={{POSITION_SYMBOL,native_symbol}};native_positions.push_back(p);
 NativeRow o;o.ticket=10000000000000003UL;o.integers={{ORDER_POSITION_ID,0},{ORDER_MAGIC,0},{ORDER_TYPE,2},{ORDER_STATE,1}};
 o.doubles={{ORDER_VOLUME_CURRENT,0.02},{ORDER_VOLUME_INITIAL,0.02},{ORDER_PRICE_OPEN,1.09},{ORDER_SL,0},{ORDER_TP,0}};o.strings={{ORDER_SYMBOL,native_symbol}};native_orders.push_back(o);
 o.ticket=10000000000000004UL;o.integers[ORDER_POSITION_ID]=10000000000000002;o.integers[ORDER_STATE]=4;native_history_orders.push_back(o);
 NativeRow d;d.ticket=10000000000000005UL;d.integers={{DEAL_ORDER,10000000000000004},{DEAL_POSITION_ID,10000000000000002},{DEAL_MAGIC,0},{DEAL_TYPE,0},{DEAL_ENTRY,0},{DEAL_TIME_MSC,(TimeGMT()+native_server_offset-10)*1000}};
 d.doubles={{DEAL_VOLUME,0.08},{DEAL_PRICE,1.1},{DEAL_PROFIT,0},{DEAL_COMMISSION,-1.25},{DEAL_SWAP,-0.5},{DEAL_FEE,-0.1}};d.strings={{DEAL_SYMBOL,native_symbol}};native_deals.push_back(d);
 d.ticket=10000000000000006UL;d.integers[DEAL_ORDER]=0;d.integers[DEAL_POSITION_ID]=0;d.integers[DEAL_TYPE]=2;d.doubles[DEAL_VOLUME]=d.doubles[DEAL_PRICE]=0;d.doubles[DEAL_PROFIT]=250;
 d.doubles[DEAL_COMMISSION]=d.doubles[DEAL_SWAP]=d.doubles[DEAL_FEE]=0;d.strings[DEAL_SYMBOL]="";native_deals.push_back(d);
}
