// Fixed-code public-fixture experiment. Not an arbitrary-code sandbox launcher.
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

class WindowsBoundary {
    const uint NO_WINDOW = 0x08000000, SUSPENDED = 4, EXTENDED = 0x80000;
    [StructLayout(LayoutKind.Sequential)] struct SA { public int length; public IntPtr sd; public int inherit; }
    [StructLayout(LayoutKind.Sequential)] struct SIDATTR { public IntPtr sid; public uint attributes; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct SI {
        public int cb; public string reserved, desktop, title;
        public uint x,y,xsize,ysize,xchars,ychars,fill,flags;
        public short show,reserved2size; public IntPtr reserved2,input,output,error;
    }
    [StructLayout(LayoutKind.Sequential)] struct SIX { public SI si; public IntPtr attributes; }
    [StructLayout(LayoutKind.Sequential)] struct PI { public IntPtr process,thread; public uint pid,tid; }
    [StructLayout(LayoutKind.Sequential)] struct BASIC {
        public long processTime,jobTime; public uint flags; public UIntPtr min,max;
        public uint active; public UIntPtr affinity; public uint priority,scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IOCOUNTERS { public ulong a,b,c,d,e,f; }
    [StructLayout(LayoutKind.Sequential)] struct LIMITS {
        public BASIC basic; public IOCOUNTERS io; public UIntPtr processMem,jobMem,peakProcess,peakJob;
    }
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr h);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr p,uint access,out IntPtr t);
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool ConvertStringSidToSid(string s,out IntPtr sid);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool CreateRestrictedToken(IntPtr old,uint flags,uint dc,IntPtr ds,uint pc,IntPtr ps,uint rc,[In] SIDATTR[] rs,out IntPtr token);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool SetTokenInformation(IntPtr token,int info,ref SIDATTR data,int size);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(IntPtr token,int info,IntPtr data,int size,out int needed);
    [DllImport("advapi32.dll")] static extern uint GetLengthSid(IntPtr sid);
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool ConvertSidToStringSid(IntPtr sid,out IntPtr text);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetSecurityDescriptorSacl(IntPtr sd,out bool present,out IntPtr acl,out bool defaulted);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode)] static extern uint SetNamedSecurityInfo(string name,int kind,uint info,IntPtr owner,IntPtr group,IntPtr dacl,IntPtr sacl);
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool CreateProcessAsUser(IntPtr token,string app,StringBuilder cmd,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string cwd,ref SIX si,out PI pi);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CreatePipe(out IntPtr r,out IntPtr w,ref SA sa,uint size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetHandleInformation(IntPtr h,uint mask,uint flags);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr p,int count,int flags,ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool UpdateProcThreadAttribute(IntPtr p,uint flags,IntPtr attr,IntPtr value,IntPtr size,IntPtr old,IntPtr returned);
    [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr p);
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr sa,string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr j,int info,ref LIMITS limits,int size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr j,IntPtr p);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr h);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr h,uint code);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr h,uint ms);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr h,out uint code);
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string s,uint revision,out IntPtr sd,IntPtr size);
    [DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern IntPtr CreateDesktop(string name,IntPtr device,IntPtr mode,uint flags,uint access,ref SA sa);
    [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr desktop);

    static void Check(bool result,string operation) {
        if (!result) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(),operation);
    }
    static void Close(ref IntPtr handle) { if(handle!=IntPtr.Zero) { CloseHandle(handle); handle=IntPtr.Zero; } }
    static string Quote(string s) { if(s.Contains("\"")) throw new Exception("quote in path"); return "\""+s+"\""; }

    // Caller exclusively creates this scratch tree first. Never call on existing host resources.
    static void Protect(string path,bool directory,bool readable) {
        FileSystemSecurity acl = directory ? (FileSystemSecurity)new DirectorySecurity() : new FileSecurity();
        acl.SetAccessRuleProtection(true,false);
        acl.SetOwner(WindowsIdentity.GetCurrent().User);
        InheritanceFlags inherit=directory?(InheritanceFlags.ContainerInherit|InheritanceFlags.ObjectInherit):InheritanceFlags.None;
        acl.AddAccessRule(new FileSystemAccessRule(WindowsIdentity.GetCurrent().User,FileSystemRights.FullControl,inherit,PropagationFlags.None,AccessControlType.Allow));
        acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier("S-1-5-18"),FileSystemRights.FullControl,inherit,PropagationFlags.None,AccessControlType.Allow));
        // OWNER RIGHTS suppresses implicit owner WRITE_DAC. Broker retains its explicit user ACE.
        acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier("S-1-3-4"),FileSystemRights.ReadPermissions,AccessControlType.Allow));
        if(readable) acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier("S-1-5-32-545"),FileSystemRights.ReadAndExecute,AccessControlType.Allow));
        if(directory) Directory.SetAccessControl(path,(DirectorySecurity)acl); else File.SetAccessControl(path,(FileSecurity)acl);
    }
    static void LabelFixture(string path) {
        IntPtr sd=IntPtr.Zero;
        try {
            Check(ConvertStringSecurityDescriptorToSecurityDescriptor("S:(ML;;NRNW;;;ME)",1,out sd,IntPtr.Zero),"fixture label descriptor");
            bool present,def; IntPtr sacl;
            Check(GetSecurityDescriptorSacl(sd,out present,out sacl,out def),"fixture SACL");
            if(!present) throw new Exception("label absent");
            uint error=SetNamedSecurityInfo(path,1,0x10,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,sacl);
            if(error!=0) throw new System.ComponentModel.Win32Exception((int)error,"set fixture mandatory label");
        } finally { if(sd!=IntPtr.Zero) LocalFree(sd); }
    }
    static string IntegritySid(IntPtr token) {
        int size; GetTokenInformation(token,25,IntPtr.Zero,0,out size);
        IntPtr buffer=Marshal.AllocHGlobal(size),text=IntPtr.Zero;
        try {
            Check(GetTokenInformation(token,25,buffer,size,out size),"read token integrity");
            Check(ConvertSidToStringSid(Marshal.ReadIntPtr(buffer),out text),"integrity SID text");
            return Marshal.PtrToStringUni(text);
        } finally { Marshal.FreeHGlobal(buffer); if(text!=IntPtr.Zero) LocalFree(text); }
    }

    static int Launch(string root) {
        string exe=System.Reflection.Assembly.GetExecutingAssembly().Location;
        if(!Path.GetFullPath(exe).StartsWith(Path.GetFullPath(root)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))
            throw new Exception("executable must be inside new scratch root");
        exe=Path.Combine(root,"windows_probe.exe");
        Protect(exe,false,true);
        Protect(Path.Combine(root,"private","public.txt"),false,false);
        Protect(Path.Combine(root,"private"),true,false);
        Protect(root,true,true);
        LabelFixture(Path.Combine(root,"private","public.txt"));
        LabelFixture(Path.Combine(root,"private"));
        IntPtr original=IntPtr.Zero,restricted=IntPtr.Zero,sid=IntPtr.Zero,job=IntPtr.Zero;
        IntPtr childIn=IntPtr.Zero,parentIn=IntPtr.Zero,parentOut=IntPtr.Zero,childOut=IntPtr.Zero;
        IntPtr attrs=IntPtr.Zero,handles=IntPtr.Zero,env=IntPtr.Zero;
        IntPtr desktop=IntPtr.Zero,desktopSd=IntPtr.Zero;
        PI pi=new PI(); bool attrsReady=false;
        try {
            Check(OpenProcessToken(GetCurrentProcess(),0x000F01FF,out original),"open token");
            Check(ConvertStringSidToSid("S-1-16-4096",out sid),"low integrity SID");
            Check(CreateRestrictedToken(original,1,0,IntPtr.Zero,0,IntPtr.Zero,0,null,out restricted),"remove token privileges");
            SIDATTR low=new SIDATTR{sid=sid,attributes=0x20};
            Check(SetTokenInformation(restricted,25,ref low,Marshal.SizeOf(typeof(SIDATTR))+(int)GetLengthSid(sid)),"set low integrity");
            if(IntegritySid(restricted)!="S-1-16-4096") throw new Exception("low integrity absent");
            SA sa=new SA{length=Marshal.SizeOf(typeof(SA)),inherit=1};
            Check(CreatePipe(out childIn,out parentIn,ref sa,0),"stdin pipe");
            Check(CreatePipe(out parentOut,out childOut,ref sa,0),"stdout pipe");
            Check(SetHandleInformation(parentIn,1,0),"parent stdin noninherit");
            Check(SetHandleInformation(parentOut,1,0),"parent stdout noninherit");
            IntPtr size=IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero,1,0,ref size);
            attrs=Marshal.AllocHGlobal(size);
            Check(InitializeProcThreadAttributeList(attrs,1,0,ref size),"attribute list"); attrsReady=true;
            handles=Marshal.AllocHGlobal(IntPtr.Size*2);
            Marshal.WriteIntPtr(handles,0,childIn); Marshal.WriteIntPtr(handles,IntPtr.Size,childOut);
            Check(UpdateProcThreadAttribute(attrs,0,new IntPtr(0x20002),handles,new IntPtr(IntPtr.Size*2),IntPtr.Zero,IntPtr.Zero),"handle whitelist");
            SIX startup=new SIX(); startup.si.cb=Marshal.SizeOf(typeof(SIX)); startup.attributes=attrs;
            startup.si.flags=0x100; startup.si.input=childIn; startup.si.output=childOut; startup.si.error=childOut;
            string stationName="hummbl_lab_"+Guid.NewGuid().ToString("N");
            string desktopAcl="D:P(A;;GA;;;"+WindowsIdentity.GetCurrent().User.Value+")S:(ML;;NW;;;LW)";
            Check(ConvertStringSecurityDescriptorToSecurityDescriptor(desktopAcl,1,out desktopSd,IntPtr.Zero),"desktop ACL");
            SA desktopSa=new SA{length=Marshal.SizeOf(typeof(SA)),sd=desktopSd,inherit=0};
            desktop=CreateDesktop(stationName,IntPtr.Zero,IntPtr.Zero,0,0x1FF,ref desktopSa);
            if(desktop==IntPtr.Zero) Check(false,"create private desktop");
            startup.si.desktop=stationName;
            // The fixed worker is console-only; no arbitrary untrusted program is accepted.
            // Minimal environment: no inherited credentials, profile variables or provider keys.
            string system=Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            env=Marshal.StringToHGlobalUni("SystemRoot="+system+"\0WINDIR="+system+"\0\0");
            Check(CreateProcessAsUser(restricted,exe,new StringBuilder(Quote(exe)),
                  IntPtr.Zero,IntPtr.Zero,true,NO_WINDOW|SUSPENDED|EXTENDED|0x400,env,root,ref startup,out pi),"create restricted worker");
            job=CreateJobObject(IntPtr.Zero,null); if(job==IntPtr.Zero) Check(false,"create job");
            LIMITS limits=new LIMITS(); limits.basic.flags=0x2000|8; limits.basic.active=1;
            Check(SetInformationJobObject(job,9,ref limits,Marshal.SizeOf(typeof(LIMITS))),"job limits");
            Check(AssignProcessToJobObject(job,pi.process),"assign suspended worker to job");
            IntPtr observed;
            Check(OpenProcessToken(pi.process,8,out observed),"inspect child token");
            string childIntegrity=IntegritySid(observed); CloseHandle(observed);
            if(childIntegrity!="S-1-16-4096") throw new Exception("child integrity is not low");
            Console.WriteLine("TOKEN|low_integrity=true|pid="+pi.pid+"|job_active_limit=1|handles=2|desktop=private");
            if(ResumeThread(pi.thread)==0xFFFFFFFF) Check(false,"resume");
            Close(ref childIn); Close(ref childOut);
            using(var reader=new StreamReader(new FileStream(new SafeFileHandle(parentOut,true),FileAccess.Read)))
            using(var writer=new StreamWriter(new FileStream(new SafeFileHandle(parentIn,true),FileAccess.Write))) {
                parentOut=parentIn=IntPtr.Zero; writer.AutoFlush=true;
                string line;
                while((line=reader.ReadLine())!=null) {
                    if(line.Length>8192) throw new Exception("oversize worker record");
                    Console.WriteLine(line);
                    if(line.StartsWith("REQUEST|",StringComparison.Ordinal)) {
                        string response=Console.ReadLine();
                        if(response==null || response.Length>4096) throw new Exception("invalid broker response");
                        writer.WriteLine(response);
                    }
                }
            }
            if(WaitForSingleObject(pi.process,5000)!=0) throw new Exception("child exit timeout");
            uint exit; Check(GetExitCodeProcess(pi.process,out exit),"exit code");
            Console.WriteLine("EXIT|"+exit); return (int)exit;
        } finally {
            if(pi.process!=IntPtr.Zero && WaitForSingleObject(pi.process,0)!=0) TerminateProcess(pi.process,99);
            Close(ref job); Close(ref pi.thread); Close(ref pi.process);
            Close(ref childIn); Close(ref childOut); Close(ref parentIn); Close(ref parentOut);
            Close(ref restricted); Close(ref original);
            if(sid!=IntPtr.Zero) LocalFree(sid);
            if(attrsReady) DeleteProcThreadAttributeList(attrs);
            if(attrs!=IntPtr.Zero) Marshal.FreeHGlobal(attrs);
            if(handles!=IntPtr.Zero) Marshal.FreeHGlobal(handles);
            if(env!=IntPtr.Zero) Marshal.FreeHGlobal(env);
            if(desktop!=IntPtr.Zero) CloseDesktop(desktop);
            if(desktopSd!=IntPtr.Zero) LocalFree(desktopSd);
        }
    }
    static int Main(string[] args) {
        try {
            if(args.Length!=2 || args[0]!="launch") throw new Exception("launch and scratch root required");
            return Launch(args[1]);
        } catch(Exception e) {
            var win=e as System.ComponentModel.Win32Exception;
            Console.Error.WriteLine("ERROR|"+e.GetType().Name+"|"+(win==null?"unknown":win.NativeErrorCode.ToString())+"|"+e.Message); return 2;
        }
    }
}
