#!/bin/bash
# macOS system-tools-only bootstrap. Exit 3 = no release, 4 = check needs install.
set -euo pipefail
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
root="$(cd "$(dirname "$0")/.." && pwd -P)"
check=false
while (($#)); do
  case "$1" in --root) root="$2"; shift 2;; --check) check=true; shift;; *) echo "Unknown bootstrap option: $1" >&2; exit 1;; esac
done
root="$(cd "$root" && pwd -P)"
[[ $(/usr/bin/uname -s) == Darwin && $(/usr/bin/uname -m) == arm64 ]] || { echo 'Native runtime requires macOS arm64.' >&2; exit 1; }
# JXA/Foundation ships with macOS; use property indexing, not plutil keypaths
# (platform keys contain hyphens). ZIP metadata is read in bounded chunks.
native() {
/usr/bin/osascript -l JavaScript - "$@" <<'JXA'
ObjC.import('Foundation');
function fail(s) { throw Error(s); }
function bytes(d) {
 var s=ObjC.unwrap(d.base64EncodedStringWithOptions(0)), chars='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/', a=[], v=0, bits=0;
 for(var i=0;i<s.length;i++){var n=chars.indexOf(s[i]);if(n<0)break;v=(v<<6)|n;bits+=6;if(bits>=8){bits-=8;a.push((v>>bits)&255);}}return a;
}
function run(args) {
 if(args[0]==='manifest') {
  var raw=$.NSString.stringWithContentsOfFileEncodingError(args[1],$.NSUTF8StringEncoding,null);
  if(!raw)fail('Cannot read runtime manifest');
  var m=JSON.parse(ObjC.unwrap(raw));
  if(m.schemaVersion!==1 || !m.platforms || Array.isArray(m.platforms) || typeof m.platforms!=='object')fail('Unsupported runtime manifest');
  if(!Object.prototype.hasOwnProperty.call(m.platforms,'macos-arm64'))return 'ABSENT';
  var e=m.platforms['macos-arm64'];
  if(!e || !/^[a-f0-9]{64}$/.test(e.sha256) || !/^[a-f0-9]{64}$/.test(e.requirementsSha256) || !Number.isInteger(e.bytes) || e.bytes<=0 || e.bytes>2147483648 || !Array.isArray(e.urls) || e.urls.length<1 || e.urls.length>4)fail('Invalid runtime entry');
  e.urls.forEach(function(u){if(typeof u!=='string'||!/^https:\/\/[^\s/@:#?]+(?::[0-9]+)?(?:\/[^\s#]*)?$/.test(u))fail('Invalid HTTPS mirror');});
  return [e.sha256,e.bytes,e.requirementsSha256].concat(e.urls).join('\n');
 }
 var f=$.NSFileHandle.fileHandleForReadingAtPath(args[1]);if(!f)fail('Cannot read ZIP');
 var length=Number(f.seekToEndOfFile);
 function read(p,n){if(p<0||n<0||p+n>length)fail('Truncated ZIP');f.seekToFileOffset(p);var a=bytes(f.readDataOfLength(n));if(a.length!==n)fail('Truncated ZIP');return a;}
 function u16(a,p){return a[p]+a[p+1]*256;}
 function u32(a,p){return u16(a,p)+u16(a,p+2)*65536;}
 function name(a){var s='';a.forEach(function(b){s+='%'+('0'+b.toString(16)).slice(-2);});try{return decodeURIComponent(s);}catch(e){fail('ZIP names must be UTF-8/ASCII');}}
 var tail=read(Math.max(0,length-65557),Math.min(length,65557)), end=-1;
 for(var i=tail.length-22;i>=0;i--)if(u32(tail,i)===0x06054b50 && i+22+u16(tail,i+20)===tail.length){end=i;break;}
 if(end<0)fail('ZIP end record missing');
 var count=u16(tail,end+10), size=u32(tail,end+12), offset=u32(tail,end+16), endpos=length-tail.length+end;
 if(u16(tail,end+4)||u16(tail,end+6)||u16(tail,end+8)!==count||count===65535||offset+size!==endpos)fail('Multi-disk/ZIP64 or inconsistent ZIP unsupported');
 var p=offset,total=0,seen={},paths={},execs=[],ranges=[],members=[];
 for(var i=0;i<count;i++){
  var h=read(p,46);if(u32(h,0)!==0x02014b50)fail('Bad ZIP directory');
  var flags=u16(h,8), method=u16(h,10), packed=u32(h,20), expanded=u32(h,24), nl=u16(h,28), extra=u16(h,30), comment=u16(h,32), attr=u32(h,38), local=u32(h,42);
  if(flags&1 || (method!==0&&method!==8) || packed===4294967295 || expanded===4294967295 || u16(h,34))fail('Unsupported ZIP member');
  var raw=read(p+46,nl), n=name(raw), dir=n.slice(-1)==='/', clean=dir?n.slice(0,-1):n;
  if(!clean || /[\\:*?"<>|\x00-\x1f\x7f]/.test(n) || n[0]==='/')fail('Unsafe archive path');
  var parts=clean.split('/');parts.forEach(function(x){if(!x||x==='.'||x==='..'||/[ .]$/.test(x)||/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$/i.test(x))fail('Unsafe archive path');});
  var key=clean.toLowerCase();if(seen[key])fail('Duplicate archive path');seen[key]=true;
  for(var j=1;j<=parts.length;j++){var path=parts.slice(0,j).join('/'), k=path.toLowerCase(), kind=j<parts.length||dir?'dir':'file';if(paths[k]&&(paths[k].name!==path||paths[k].kind!==kind))fail('Conflicting archive paths');paths[k]={name:path,kind:kind};}
  var mode=Math.floor(attr/65536), type=mode&61440;
  if((type!==0&&type!==(dir?16384:32768)) || (attr&1024))fail('Archive links/special files forbidden');
  total+=expanded;if(total>6442450944 || (dir&&expanded))fail('Archive expansion exceeds limit');
  var lh=read(local,30);if(u32(lh,0)!==0x04034b50 || u16(lh,6)!==flags || u16(lh,8)!==method || u16(lh,26)!==nl || name(read(local+30,nl))!==n)fail('ZIP local header mismatch');
  var finish=local+30+nl+u16(lh,28)+packed;if(finish>offset)fail('Overlapping ZIP directory');ranges.push([local,finish]);
  if(!dir && (mode&73))execs.push(clean);
  members.push({name:clean,dir:dir,size:expanded});
  p+=46+nl+extra+comment;
 }
 if(p!==offset+size)fail('ZIP directory size mismatch');
 ranges.sort(function(a,b){return a[0]-b[0];});for(var i=1;i<ranges.length;i++)if(ranges[i][0]<ranges[i-1][1])fail('Overlapping ZIP members');
 f.closeFile;
 if(args.length>2){
  // Stream one unzip process into bounded files in central-directory order.
  // Never let an extractor choose destination paths or write unbounded output.
  var dest=args[2], fm=$.NSFileManager.defaultManager;
  if(fm.fileExistsAtPath(dest))fail('Extraction destination must be new');
  if(!fm.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(dest,true,$({}),null))fail('Cannot create extraction directory');
  var task=$.NSTask.alloc.init, pipe=$.NSPipe.pipe;
  task.launchPath='/bin/bash';task.arguments=['-c','ulimit -t 600; exec /usr/bin/unzip -p "$1"','bootstrap-unzip',args[1]];
  task.standardOutput=pipe; task.standardInput=$.NSFileHandle.fileHandleWithNullDevice;
  var input=pipe.fileHandleForReading;
  task.launch;
  try {
   members.forEach(function(m){
    var target=dest+'/'+m.name, parent=m.dir?target:target.slice(0,target.lastIndexOf('/'));
    if(!fm.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(parent,true,$({}),null))fail('Cannot create member directory');
    if(m.dir)return;
    if(!fm.createFileAtPathContentsAttributes(target,$.NSData.data,$({})))fail('Cannot create member');
    var out=$.NSFileHandle.fileHandleForWritingAtPath(target), remaining=m.size;
    try {while(remaining>0){var d=input.readDataOfLength(Math.min(1048576,remaining)), n=Number(d.length);if(!n)fail('Truncated ZIP output');out.writeData(d);remaining-=n;}} finally {out.closeFile;}
   });
   if(Number(input.readDataOfLength(1).length))fail('ZIP output exceeds declared expansion');
   task.waitUntilExit;if(task.terminationStatus!==0)fail('ZIP extraction/CRC verification failed');
  } finally {if(task.running)task.terminate;input.closeFile;}
 }
 return [total].concat(execs).join('\n');
}
JXA
}
metadata="$(native manifest "$root/distribution/source-runtime.json")"
[[ "$metadata" != ABSENT ]] || exit 3
sha=$(printf '%s\n' "$metadata" | /usr/bin/sed -n '1p')
size=$(printf '%s\n' "$metadata" | /usr/bin/sed -n '2p')
req=$(printf '%s\n' "$metadata" | /usr/bin/sed -n '3p')
[[ $(/usr/bin/shasum -a 256 "$root/requirements.txt" | /usr/bin/awk '{print $1}') == "$req" ]] || { echo 'Runtime requirements fingerprint mismatch.' >&2; exit 1; }
if $check; then echo 'Check requires an installed Python/venv. Run install.sh without --check to bootstrap the published runtime.' >&2; exit 4; fi
cache="$HOME/Library/Caches/Mofish/source-runtime"
/bin/mkdir -p "$cache"
cache="$(cd "$cache" && pwd -P)"
case "$cache/" in "$root/"*) echo 'Runtime cache must be outside repository.' >&2; exit 1;; esac
/bin/mkdir -p "$cache/archives" "$cache/bootstrap"
for dir in "$cache/archives" "$cache/bootstrap"; do [[ ! -L "$dir" ]] || { echo 'Cache subdirectory must not be a link.' >&2; exit 1; }; done
archive="$cache/archives/$sha.bundle"
stage=$(/usr/bin/mktemp -d "$cache/bootstrap/$sha.XXXXXXXX")
trap '/bin/rm -rf "$stage"' EXIT
valid_archive() { [[ -f "$archive" && ! -L "$archive" && $(/usr/bin/stat -f %z "$archive") == "$size" && $(/usr/bin/shasum -a 256 "$archive" | /usr/bin/awk '{print $1}') == "$sha" ]]; }
space() { local free; free=$(/bin/df -Pk "$cache" | /usr/bin/awk 'END{print $4}'); ((free * 1024 >= $1 + 67108864)) || { echo 'Insufficient runtime cache disk space.' >&2; exit 1; }; }
if ! valid_archive; then
  [[ ! -e "$archive" && ! -L "$archive" ]] || { echo 'Invalid cached bundle preserved; remove it explicitly and retry.' >&2; exit 1; }
  space "$size"
  deadline=$((SECONDS + 900)); success=false
  for attempt in 1 2 3; do
    while IFS= read -r url; do
      remaining=$((deadline - SECONDS)); ((remaining > 0)) || break
      echo "Runtime download attempt $attempt/3" >&2
      if (ulimit -f "$(((size + 1023) / 1024))"; /usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 30 --max-time "$remaining" --max-filesize "$size" --silent --show-error --output "$stage/download" "$url") && [[ $(/usr/bin/stat -f %z "$stage/download") == "$size" && $(/usr/bin/shasum -a 256 "$stage/download" | /usr/bin/awk '{print $1}') == "$sha" ]]; then
        /bin/mv -n "$stage/download" "$archive"; success=true; break
      fi
    done < <(printf '%s\n' "$metadata" | /usr/bin/sed '1,3d')
    $success && break
  done
  valid_archive || { echo 'Runtime download failed SHA/size verification.' >&2; exit 1; }
fi
inventory="$(native zip "$archive")"
space "$(printf '%s\n' "$inventory" | /usr/bin/sed -n '1p')"
echo 'Extracting verified bootstrap runtime…' >&2
native zip "$archive" "$stage/runtime" >/dev/null
while IFS= read -r executable; do [[ -z "$executable" ]] || /bin/chmod 755 "$stage/runtime/$executable"; done < <(printf '%s\n' "$inventory" | /usr/bin/sed '1d')
python="$stage/runtime/python/bin/python3"
[[ -f "$python" && -x "$python" && ! -L "$python" ]] || { echo 'Bundle missing executable Python.' >&2; exit 1; }
# Isolated mode avoids user site/PYTHONPATH; official helper owns final extraction/seal.
"$python" -I -B -X utf8 -c 'import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from scripts.source_runtime import prepare_runtime,python_path; r=prepare_runtime(Path(sys.argv[1])); assert r is not None; print(python_path(r))' "$root"
