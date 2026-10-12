// Shared MQL5 laboratory core. No terminal/broker APIs or floating point.
#ifndef TRD_CORE_MQH
#define TRD_CORE_MQH

int TrdNibble(const int c)
{
   if(c>=48 && c<=57) return c-48;
   if(c>=97 && c<=102) return c-87;
   return -1;
}
string TrdHexByte(const uint n)
{
   const string digits="0123456789abcdef";
   return StringSubstr(digits,(int)((n>>4)&15),1)+StringSubstr(digits,(int)(n&15),1);
}
bool TrdHex(const string s)
{
   if(StringLen(s)%2!=0) return false;
   for(int i=0;i<StringLen(s);i++) if(TrdNibble(StringGetCharacter(s,i))<0) return false;
   return true;
}
uint TrdByte(const string s,const int i)
{
   return (uint)(16*TrdNibble(StringGetCharacter(s,2*i))+TrdNibble(StringGetCharacter(s,2*i+1)));
}
string TrdAsciiHex(const string s)
{
   string out="";
   for(int i=0;i<StringLen(s);i++)
   {
      uint c=StringGetCharacter(s,i);
      if(c>127) return "";
      out+=TrdHexByte(c);
   }
   return out;
}
string TrdHexAscii(const string s)
{
   if(!TrdHex(s)) return "";
   string out="";
   for(int i=0;i<StringLen(s)/2;i++)
   {
      uint c=TrdByte(s,i);
      if(c==0 || c>127) return "";
      out+=CharToString((uchar)c);
   }
   return out;
}
uint TrdRor(const uint x,const int n) { return (x>>n)|(x<<(32-n)); }
string TrdSha256(const string bytes)
{
   if(!TrdHex(bytes) || StringLen(bytes)>131072) return "";
   string data=bytes+"80";
   while((StringLen(data)/2)%64!=56) data+="00";
   long bits=(long)StringLen(bytes)*4;
   for(int i=7;i>=0;i--) data+=TrdHexByte((uint)((bits>>(8*i))&255));
   uint k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
   0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
   0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
   0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
   0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
   0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
   0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
   0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
   uint h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
   for(int offset=0;offset<StringLen(data)/2;offset+=64)
   {
      uint w[64];
      for(int i=0;i<16;i++)
         w[i]=(TrdByte(data,offset+4*i)<<24)|(TrdByte(data,offset+4*i+1)<<16)|(TrdByte(data,offset+4*i+2)<<8)|TrdByte(data,offset+4*i+3);
      for(int i=16;i<64;i++)
         w[i]=w[i-16]+(TrdRor(w[i-15],7)^TrdRor(w[i-15],18)^(w[i-15]>>3))+w[i-7]+(TrdRor(w[i-2],17)^TrdRor(w[i-2],19)^(w[i-2]>>10));
      uint a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],j=h[7];
      for(int i=0;i<64;i++)
      {
         uint t1=j+(TrdRor(e,6)^TrdRor(e,11)^TrdRor(e,25))+((e&f)^((~e)&g))+k[i]+w[i];
         uint t2=(TrdRor(a,2)^TrdRor(a,13)^TrdRor(a,22))+((a&b)^(a&c)^(b&c));
         j=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
      }
      h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=j;
   }
   string out="";
   for(int i=0;i<8;i++) for(int j=3;j>=0;j--) out+=TrdHexByte((h[i]>>(8*j))&255);
   return out;
}
string TrdHash(const string ascii) { return TrdSha256(TrdAsciiHex(ascii)); }
string TrdHmac(const string key_hex,const string bytes)
{
   if(!TrdHex(key_hex) || !TrdHex(bytes)) return "";
   string key=key_hex;
   if(StringLen(key)>128) key=TrdSha256(key);
   while(StringLen(key)<128) key+="00";
   string inner="",outer="";
   for(int i=0;i<64;i++) { inner+=TrdHexByte(TrdByte(key,i)^0x36);outer+=TrdHexByte(TrdByte(key,i)^0x5c); }
   return TrdSha256(outer+TrdSha256(inner+bytes));
}
bool TrdEqual(const string a,const string b)
{
   if(StringLen(a)!=64 || StringLen(b)!=64 || !TrdHex(a) || !TrdHex(b)) return false;
   uint diff=0;
   for(int i=0;i<64;i++) diff|=StringGetCharacter(a,i)^StringGetCharacter(b,i);
   return diff==0;
}
bool TrdSelfTest()
{
   string key="",message="4869205468657265";
   for(int i=0;i<20;i++) key+="0b";
   return TrdHash("abc")=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
      && TrdHmac(key,message)=="b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7";
}
bool TrdToken(const string s)
{
   if(StringLen(s)<1 || StringLen(s)>64) return false;
   for(int i=0;i<StringLen(s);i++)
   {
      int c=StringGetCharacter(s,i);
      if(!((c>=48 && c<=57)||(c>=65 && c<=90)||(c>=97 && c<=122)||c==45||c==95)) return false;
   }
   return true;
}
bool TrdUnsigned(const string s,long &n)
{
   n=0;
   if(StringLen(s)<1 || StringLen(s)>19 || (StringLen(s)>1 && StringGetCharacter(s,0)==48)) return false;
   for(int i=0;i<StringLen(s);i++)
   {
      int digit=StringGetCharacter(s,i)-48;
      if(digit<0 || digit>9 || n>(9223372036854775807-digit)/10) return false;
      n=n*10+digit;
   }
   return true;
}
// Exact lab arithmetic: five decimals, upper bound one million. Extra zero digits are accepted.
bool TrdScaledDecimal(const string s,long &n,const int places)
{
   n=0;
   if(StringLen(s)<1 || StringLen(s)>24) return false;
   int dot=StringFind(s,"."),whole=dot<0?StringLen(s):dot;
   if(whole<1 || whole>7 || (whole>1 && StringGetCharacter(s,0)==48)) return false;
   for(int i=0;i<whole;i++)
   {
      int d=StringGetCharacter(s,i)-48;
      if(d<0||d>9) return false;
      n=n*10+d;
   }
   long scale=1;
   for(int i=0;i<places;i++) scale*=10;
   n*=scale;
   if(dot>=0)
   {
      if(dot==StringLen(s)-1) return false;
      long place=scale/10;
      for(int i=dot+1;i<StringLen(s);i++)
      {
         int d=StringGetCharacter(s,i)-48;
         if(d<0||d>9||(place==0 && d!=0)) return false;
         n+=d*place;place/=10;
      }
   }
   return n<=1000000*scale;
}
bool TrdDecimal(const string s,long &n) { return TrdScaledDecimal(s,n,5); }
string TrdMoney(const long n)
{
   long absolute=n<0?-n:n;
   string fraction=IntegerToString(absolute%100000);
   while(StringLen(fraction)<5) fraction="0"+fraction;
   return (n<0?"-":"")+IntegerToString(absolute/100000)+"."+fraction;
}
string TrdUuid(const string seed)
{
   string h=TrdHash(seed);
   return StringSubstr(h,0,8)+"-"+StringSubstr(h,8,4)+"-4"+StringSubstr(h,13,3)+"-a"+StringSubstr(h,17,3)+"-"+StringSubstr(h,20,12);
}
bool TrdUuidValid(const string s)
{
   if(StringLen(s)!=36) return false;
   for(int i=0;i<36;i++)
      if(i==8||i==13||i==18||i==23) { if(StringGetCharacter(s,i)!=45) return false; }
      else if(TrdNibble(StringGetCharacter(s,i))<0) return false;
   return true;
}
string TrdQuote(const string s)
{
   string out="\"";
   for(int i=0;i<StringLen(s);i++)
   {
      int c=StringGetCharacter(s,i);
      if(c<32||c>126) return "";
      if(c==34||c==92) out+="\\";
      out+=CharToString((uchar)c);
   }
   return out+"\"";
}

// Bounded strict ASCII lab JSON. Financial numbers must be strings. Unicode outside
// the supported lab schema is rejected; signatures still operate on exact byte hex.
class TrdJson
{
public:
   string source;
   int count,cursor;
   int begin[8192],end[8192],parent[8192],kind[8192];
   string name[8192],value[8192];
   void Space() { while(cursor<StringLen(source) && (StringGetCharacter(source,cursor)==32||StringGetCharacter(source,cursor)==10||StringGetCharacter(source,cursor)==13||StringGetCharacter(source,cursor)==9)) cursor++; }
   bool ReadString(string &out)
   {
      out="";
      if(cursor>=StringLen(source)||StringGetCharacter(source,cursor++)!=34) return false;
      while(cursor<StringLen(source))
      {
         int c=StringGetCharacter(source,cursor++);
         if(c==34) return StringLen(out)<=8192;
         if(c<32||c>126) return false;
         if(c==92)
         {
            if(cursor>=StringLen(source)) return false;
            c=StringGetCharacter(source,cursor++);
            if(c==117)
            {
               int code=0;
               for(int j=0;j<4;j++)
               {
                  if(cursor>=StringLen(source)) return false;
                  int nibble=TrdNibble(StringGetCharacter(source,cursor++));
                  if(nibble<0) return false;
                  code=16*code+nibble;
               }
               if(code<32||code>126) return false;
               c=code;
            }
            else if(c!=34 && c!=92 && c!=47) return false;
         }
         out+=CharToString((uchar)c);
         if(StringLen(out)>8192) return false;
      }
      return false;
   }
   int Node(const int depth,const int owner,const string key)
   {
      Space();
      if(depth>12||count>=8192||cursor>=StringLen(source)) return -1;
      int node=count++;begin[node]=cursor;parent[node]=owner;name[node]=key;value[node]="";
      int c=StringGetCharacter(source,cursor);
      if(c==123||c==91)
      {
         kind[node]=c==123?1:2;cursor++;Space();int children=0,closing=c==123?125:93;
         if(cursor<StringLen(source)&&StringGetCharacter(source,cursor)==closing) cursor++;
         else while(true)
         {
            string field="";
            if(c==123)
            {
               if(!ReadString(field)) return -1;
               for(int i=node+1;i<count;i++) if(parent[i]==node&&name[i]==field) return -1;
               Space();if(cursor>=StringLen(source)||StringGetCharacter(source,cursor++)!=58) return -1;
            }
            if(++children>(c==123?128:1000)||Node(depth+1,node,field)<0) return -1;
            Space();if(cursor>=StringLen(source)) return -1;
            int delimiter=StringGetCharacter(source,cursor++);
            if(delimiter==closing) break;
            if(delimiter!=44) return -1;
            Space();
         }
      }
      else if(c==34) { kind[node]=3;if(!ReadString(value[node])) return -1; }
      else
      {
         while(cursor<StringLen(source))
         {
            c=StringGetCharacter(source,cursor);
            if(c==44||c==125||c==93||c==32||c==9||c==10||c==13) break;
            cursor++;
         }
         value[node]=StringSubstr(source,begin[node],cursor-begin[node]);
         if(value[node]=="true"||value[node]=="false") kind[node]=4;
         else if(value[node]=="null") kind[node]=5;
         else { long n;kind[node]=6;if(!TrdUnsigned(value[node],n)) return -1; }
      }
      end[node]=cursor;return node;
   }
   bool Parse(const string s)
   {
      source=s;count=0;cursor=0;
      if(StringLen(s)<1||StringLen(s)>65536||Node(0,-1,"")!=0) return false;
      Space();return cursor==StringLen(s)&&kind[0]==1;
   }
   int Field(const string key,const int owner=0)
   {
      for(int i=owner+1;i<count;i++) if(parent[i]==owner && name[i]==key) return i;
      return -1;
   }
   string Get(const string key,const int owner=0)
   {
      int n=Field(key,owner);return n<0?"":value[n];
   }
   string Raw(const int n) { return n<0?"":StringSubstr(source,begin[n],end[n]-begin[n]); }
   bool Fields(const string allowed,const int owner=0)
   {
      int expected=0;
      for(int i=0;i<StringLen(allowed);i++) if(StringGetCharacter(allowed,i)==124) expected++;
      int actual=0;
      for(int i=owner+1;i<count;i++) if(parent[i]==owner)
      {
         if(StringFind(allowed,"|"+name[i]+"|")<0) return false;
         actual++;
      }
      return actual==expected-1;
   }
   string Replace(const string field,const string raw)
   {
      int n=Field(field);
      if(n<0) return "";
      return StringSubstr(source,0,begin[n])+raw+StringSubstr(source,end[n]);
   }
};
string TrdFrame(const string env,const string bridge,const string instance,const string key,const string journal,
                const string sequence,const string issued,const string expires,const string path,const int status,
                const string direction,const string body_hex)
{
   long seq,start,finish;
   if(!TrdToken(env)||!TrdToken(bridge)||!TrdToken(instance)||!TrdToken(key)||!TrdToken(journal)
      ||!TrdUnsigned(sequence,seq)||seq<1||!TrdUnsigned(issued,start)||start<1||!TrdUnsigned(expires,finish)
      ||finish<=start||finish-start>10||!TrdHex(body_hex)||StringLen(body_hex)>131072
      ||(path!="/bridge/v1/snapshot"&&path!="/bridge/v1/poll"&&path!="/bridge/v1/events")
      ||(direction!="REQUEST"&&direction!="RESPONSE")) return "";
   return "TRD-BRIDGE-V1\n"+direction+"\n"+env+"\n"+bridge+"\n"+instance+"\n"+key+"\n"+journal+
      "\nPOST\n"+path+"\n"+IntegerToString(status)+"\n"+sequence+"\n"+issued+"\n"+expires+"\n"+TrdSha256(body_hex)+"\n";
}
string TrdBase64(const string s)
{
   const string alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
   string out="";uint acc=0;int bits=0,padding=0;
   if(StringLen(s)%4!=0||StringLen(s)>87384) return "";
   for(int i=0;i<StringLen(s);i++)
   {
      int c=StringGetCharacter(s,i);
      if(c==61) { padding++;if(padding>2||i<StringLen(s)-2) return "";continue; }
      if(padding>0) return "";
      int digit=StringFind(alphabet,CharToString((uchar)c));
      if(digit<0) return "";
      acc=(acc<<6)|(uint)digit;bits+=6;
      if(bits>=8) { bits-=8;out+=TrdHexByte((acc>>bits)&255); }
   }
   if((padding==1&&bits!=2)||(padding==2&&bits!=4)||(padding==0&&bits!=0)||(bits>0&&(acc&((1<<bits)-1))!=0)) return "";
   return out;
}
#endif
