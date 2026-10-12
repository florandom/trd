// Test-only MQL platform shim. Shared EA/core source remains the implementation.
// This is not MetaEditor, WebRequest, or a certification of Windows file semantics.
#pragma once
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <iostream>
#include <map>
#include <string>
#include <vector>
#include <sys/file.h>
#include <unistd.h>
using string=std::string;using uchar=unsigned char;using uint=uint32_t;using datetime=long;
constexpr int INVALID_HANDLE=-1,FILE_READ=1,FILE_WRITE=2,FILE_TXT=4,FILE_ANSI=8,FILE_COMMON=16,CP_UTF8=65001;
constexpr int TIME_DATE=1,TIME_SECONDS=2,INIT_SUCCEEDED=0,INIT_FAILED=1,MQL_TESTER=1;
using ulong=unsigned long;
constexpr int TRADE_ACTION_DEAL=1,TRADE_ACTION_SLTP=6,ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,ORDER_FILLING_FOK=0,ORDER_TIME_GTC=0;
constexpr uint TRADE_RETCODE_PLACED=10008,TRADE_RETCODE_DONE=10009,TRADE_RETCODE_DONE_PARTIAL=10010,TRADE_RETCODE_REJECT=10006,TRADE_RETCODE_TIMEOUT=10012,TRADE_RETCODE_NO_MONEY=10019,TRADE_RETCODE_CONNECTION=10031,TRADE_RETCODE_ERROR=10011;
struct MqlTradeTransaction {};
struct MqlTradeRequest {
 int action=0,type=0,type_filling=0,type_time=0;ulong magic=0,order=0,position=0,position_by=0,deviation=0;
 string symbol,comment;double volume=0,price=0,stoplimit=0,sl=0,tp=0;datetime expiration=0;
};
struct MqlTradeResult { uint retcode=0,request_id=0;int retcode_external=0;ulong deal=0,order=0;double volume=0,price=0; };
struct MqlTradeCheckResult { uint retcode=0; };
static int host_error=0;static string host_root;static bool host_tester=false;
int StringLen(const string &s) { return static_cast<int>(s.size()); }
string StringSubstr(const string &s,int start,int length=-1) {
 if(start<0||start>=StringLen(s)) return "";return s.substr(start,length<0?string::npos:static_cast<size_t>(length));
}
int StringGetCharacter(const string &s,int i) { return i<0||i>=StringLen(s)?0:static_cast<uchar>(s[i]); }
string CharToString(uchar c) { return string(1,static_cast<char>(c)); }
string IntegerToString(long n) { return std::to_string(n); }
int StringFind(const string &s,const string &needle,int start=0) {
 auto n=s.find(needle,static_cast<size_t>(start));return n==string::npos?-1:static_cast<int>(n);
}
int StringReplace(string &s,const string &from,const string &to) {
 int count=0;size_t pos=0;while((pos=s.find(from,pos))!=string::npos) { s.replace(pos,from.size(),to);pos+=to.size();count++; }return count;
}
void StringTrimLeft(string &s) { s.erase(0,s.find_first_not_of(" \r\n\t")); }
void StringTrimRight(string &s) { auto n=s.find_last_not_of(" \r\n\t");s.erase(n==string::npos?0:n+1); }
void StringToLower(string &s) { std::transform(s.begin(),s.end(),s.begin(),[](unsigned char c){return std::tolower(c);}); }
template<class T> int ArraySize(const std::vector<T> &a) { return static_cast<int>(a.size()); }
template<class T> int ArrayResize(std::vector<T> &a,int n) { a.resize(n);return n; }
void ResetLastError() { host_error=0; }int GetLastError() { return host_error; }
int MQLInfoInteger(int) { return host_tester?1:0; }
datetime TimeGMT() { return static_cast<long>(std::time(nullptr)); }
string TimeToString(datetime value,int flags) { std::time_t t=value;std::tm tm=*std::gmtime(&t);char buffer[32];std::strftime(buffer,sizeof(buffer),flags==TIME_DATE?"%Y.%m.%d":"%Y.%m.%d %H:%M:%S",&tm);return buffer; }
datetime StringToTime(const string &s) { std::tm tm={};if(!strptime(s.c_str(),"%Y.%m.%d %H:%M:%S",&tm)) return 0;return static_cast<long>(timegm(&tm)); }
bool EventSetTimer(int) { return true; }void EventKillTimer() {}
struct HostFile { FILE* stream;int descriptor; };
static std::map<int,HostFile> host_files;static int host_next_file=1;
int FileOpen(string path,int flags,int,uint) {
 std::replace(path.begin(),path.end(),'\\','/');auto location=std::filesystem::path(host_root)/path;
 if(flags&FILE_WRITE) std::filesystem::create_directories(location.parent_path());
 FILE* file=nullptr;
 if(flags&FILE_WRITE) { file=std::fopen(location.c_str(),"r+b");if(!file) file=std::fopen(location.c_str(),"w+b"); }
 else file=std::fopen(location.c_str(),"rb");
 if(!file) { host_error=1;return INVALID_HANDLE; }
 int fd=fileno(file);
 if(flock(fd,(flags&FILE_WRITE?LOCK_EX:LOCK_SH)|LOCK_NB)!=0) { std::fclose(file);host_error=2;return INVALID_HANDLE; }
 int handle=host_next_file++;host_files[handle]={file,fd};return handle;
}
void FileClose(int handle) { auto f=host_files.find(handle);if(f!=host_files.end()) { std::fclose(f->second.stream);host_files.erase(f); } }
long FileSize(int handle) { auto file=host_files.at(handle).stream;long pos=ftell(file);fseek(file,0,SEEK_END);long size=ftell(file);fseek(file,pos,SEEK_SET);return size; }
bool FileSeek(int handle,long offset,int origin) { return fseek(host_files.at(handle).stream,offset,origin)==0; }
bool FileIsEnding(int handle) { return ftell(host_files.at(handle).stream)>=FileSize(handle); }
string FileReadString(int handle) { string result;int c;auto file=host_files.at(handle).stream;while((c=fgetc(file))!=EOF&&c!='\n') result+=static_cast<char>(c);if(!result.empty()&&result.back()=='\r') result.pop_back();return result; }
uint FileWriteString(int handle,const string &value) { return static_cast<uint>(fwrite(value.data(),1,value.size(),host_files.at(handle).stream)); }
void FileFlush(int handle) { auto f=host_files.at(handle);if(fflush(f.stream)!=0||fsync(f.descriptor)!=0) host_error=3; }
// HTTP is an explicit loopback RPC into the Python harness, never a broker call.
int WebRequest(const string &,const string &url,const string &headers,int,const std::vector<char> &data,std::vector<char> &result,string &response_headers);
