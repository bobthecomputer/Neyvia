using System;
using System.IO;
using System.Text;
using System.Net;
using System.Net.Sockets;
using System.Collections.Generic;
using System.Threading;
using System.Windows.Forms;
using System.Drawing;
using System.Web.Script.Serialization;
// Offline Windows host, UI and loopback agent API use precisely the same Act.
class NeyviaApp : Form {
  int count=0, revision=0; Label display; string statePath; TcpListener server;
  JavaScriptSerializer json=new JavaScriptSerializer();
  Dictionary<string,object> State(){return new Dictionary<string,object>{{"count",count},{"revision",revision}};}
  object Act(string name){
    int next=count;
    switch(name){case "increment":next++;break;case "decrement":next=Math.Max(0,next-1);break;case "reset":next=0;break;default:throw new Exception("Unknown action");}
    if(next<0)throw new Exception("Count invariant failed");
    var before=State();
    // Persist before exposing the update to either side.
    File.WriteAllText(statePath+".tmp",json.Serialize(new Dictionary<string,object>{{"count",next},{"revision",revision+1}}));
    if(File.Exists(statePath))File.Replace(statePath+".tmp",statePath,null);else File.Move(statePath+".tmp",statePath);
    count=next;revision++; display.Text="Count: "+count;
    return new Dictionary<string,object>{{"ok",true},{"before",before},{"after",State()}};
  }
  NeyviaApp(int port,string root){
    statePath=Path.Combine(root,"native-state.json");
    if(File.Exists(statePath)){var saved=json.Deserialize<Dictionary<string,int>>(File.ReadAllText(statePath));count=saved["count"];revision=saved["revision"];if(count<0)throw new Exception("Invalid persisted state");}
    Text="__NAME__";Width=440;Height=360;StartPosition=FormStartPosition.Manual;Location=new Point(50,50);
    var heading=new Label{Text=Text,Left=24,Top=24,Width=370,Height=45,Font=new Font("Segoe UI",20)};Controls.Add(heading);
    display=new Label{Text="Count: "+count,Name="count",AccessibleName="Count: "+count,Left=24,Top=90,Width=370,Height=50,Font=new Font("Segoe UI",24)};Controls.Add(display);
    int x=24;
    foreach(string action in new[]{"increment","decrement","reset"}){string name=action;var button=new Button{Text=char.ToUpper(name[0])+name.Substring(1),Name=name,AccessibleName=name,Left=x,Top=170,Width=115,Height=42};button.Click+=(s,e)=>{Act(name);display.AccessibleName=display.Text;};Controls.Add(button);x+=122;}
    Controls.Add(new Label{Text="Made with Neyvia",Left=24,Top=250,Width=370});
    server=new TcpListener(IPAddress.Loopback,port);server.Start();
    var thread=new Thread(Serve);thread.IsBackground=true;thread.Start();
    FormClosed+=(s,e)=>server.Stop();
  }
  void Serve(){while(true){TcpClient client;try{client=server.AcceptTcpClient();}catch{return;}
    using(client){client.ReceiveTimeout=5000;client.SendTimeout=5000;try{
      var stream=client.GetStream();var header=new List<byte>();int b;
      while(header.Count<16384&&(b=stream.ReadByte())>=0){header.Add((byte)b);int n=header.Count;if(n>=4&&header[n-4]==13&&header[n-3]==10&&header[n-2]==13&&header[n-1]==10)break;}
      string[] lines=Encoding.ASCII.GetString(header.ToArray()).Split(new[]{"\r\n"},StringSplitOptions.None);
      string[] request=lines[0].Split(' ');int length=0;bool authorized=false,hasOrigin=false;
      foreach(string line in lines){if(line.StartsWith("Content-Length:",StringComparison.OrdinalIgnoreCase))length=int.Parse(line.Substring(15).Trim());if(line.Equals("X-Neyvia-App: 1",StringComparison.OrdinalIgnoreCase))authorized=true;if(line.StartsWith("Origin:",StringComparison.OrdinalIgnoreCase))hasOrigin=true;}
      if(!authorized||hasOrigin||length<0||length>8192)throw new Exception("Only the local SDK transport is accepted");
      byte[] bytes=new byte[length];int offset=0;while(offset<length){int read=stream.Read(bytes,offset,length-offset);if(read==0)throw new Exception("Incomplete body");offset+=read;}
      object result=null;
      Invoke(new Action(()=>{if(request[0]=="GET"&&request[1]=="/__neyvia/state")result=State();else if(request[0]=="POST"&&request[1]=="/__neyvia/act"){var args=json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(bytes));result=Act((string)args["name"]);display.AccessibleName=display.Text;}else throw new Exception("Unknown endpoint");}));
      Reply(stream,200,result);
    }catch(Exception error){try{Reply(client.GetStream(),400,new Dictionary<string,object>{{"ok",false},{"error",error.GetBaseException().Message}});}catch{}}}
  }}
  void Reply(NetworkStream stream,int status,object value){byte[] body=Encoding.UTF8.GetBytes(json.Serialize(value));byte[] header=Encoding.ASCII.GetBytes("HTTP/1.1 "+status+" OK\r\nContent-Type: application/json\r\nContent-Length: "+body.Length+"\r\nConnection: close\r\n\r\n");stream.Write(header,0,header.Length);stream.Write(body,0,body.Length);}
  [STAThread] static void Main(string[] args){int port=int.Parse(args[0]);if(port<1||port>65535)throw new Exception("Explicit port required");Application.EnableVisualStyles();Application.Run(new NeyviaApp(port,AppDomain.CurrentDomain.BaseDirectory));}
}
