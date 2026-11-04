/* Shared, optional return chime. Browser gestures unlock audio; never replay. */
(() => {
  let context = null;
  function prepare(event) {
    if (!event.isTrusted) return;
    try {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) return;
      if (!context || context.state === 'closed') context = new Audio();
      if (context.state === 'suspended') context.resume().catch(() => {});
    } catch (_) {}
  }
  document.addEventListener('pointerdown', prepare, {capture:true,passive:true});
  document.addEventListener('keydown', prepare, {capture:true});
  async function play(isCurrent=()=>true) {
    if (document.hidden || !isCurrent()) return;
    // Native delivery does not depend on WebKit's gesture-gated audio context.
    const native = window.webkit?.messageHandlers?.workbenchReturnSound;
    if (native) {
      try { if (await native.postMessage({type:'return-success'})) return; } catch (_) {}
    }
    if (document.hidden || !isCurrent() || !context) return;
    if (context.state === 'suspended') {
      try { await context.resume(); } catch (_) { return; }
    }
    if (document.hidden || !isCurrent() || context.state !== 'running') return;
    try {
      const start=context.currentTime;
      [880,1174.66].forEach((frequency,index)=>{
        const oscillator=context.createOscillator(),gain=context.createGain(),at=start+index*0.12;
        oscillator.type='sine';oscillator.frequency.setValueAtTime(frequency,at);
        gain.gain.setValueAtTime(0,at);gain.gain.linearRampToValueAtTime(0.045,at+0.012);
        gain.gain.exponentialRampToValueAtTime(0.0001,at+0.17);gain.gain.linearRampToValueAtTime(0,at+0.18);
        oscillator.connect(gain);gain.connect(context.destination);
        oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};
        oscillator.start(at);oscillator.stop(at+0.18);
      });
    } catch (_) {}
  }
  const seen=new Set();
  async function notify(key,message,success,isCurrent=()=>true) {
    if(seen.has(key))return;seen.add(key);
    // Hidden pages consume locally, but must not steal a foreground page's claim.
    if(document.hidden||!isCurrent())return;
    const deliver=()=>{
      if(document.hidden||!isCurrent())return;
      try {if(localStorage.getItem(key))return;localStorage.setItem(key,'1');} catch(_){return;}
      window.showToast(message,success?'success':'error',success?2000:4000);
      if(success)play(isCurrent).catch(()=>{});
    };
    // Same-origin exclusive lock makes the durable claim atomic across tabs.
    if(navigator.locks)await navigator.locks.request(key,deliver);
    else if(document.hasFocus())deliver();
  }
  window.WorkbenchReturnFeedback={play,notify};
})();
