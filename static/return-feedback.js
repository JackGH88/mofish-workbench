/* Text feedback and the sound primitive have independent delivery receipts. */
(() => {
  let context = null;
  function prepare(event) {
    if (!event.isTrusted) return;
    try {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) return;
      if (!context || context.state === 'closed') context = new Audio();
      if (context.state === 'suspended') context.resume().then(() => window.WorkbenchReturnSounds?.sync()).catch(() => {});
      else window.WorkbenchReturnSounds?.sync();
    } catch (_) {}
  }
  document.addEventListener('pointerdown', prepare, {capture:true,passive:true});
  document.addEventListener('keydown', prepare, {capture:true});
  async function play(isCurrent=()=>true) {
    if (!isCurrent()) return false;
    // Native delivery does not depend on WebKit's gesture-gated audio context.
    const native = window.webkit?.messageHandlers?.workbenchReturnSound;
    if (native) {
      try { if (await native.postMessage({type:'return-success'})) return true; } catch (_) {}
    }
    if (!isCurrent() || !context || context.state !== 'running') return false;
    return new Promise(resolve => {
      const nodes = [];
      let ended = 0, settled = false;
      const finish = played => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        for (const [oscillator, gain] of nodes) {
          oscillator.onended = null;
          try { oscillator.stop(); } catch (_) {}
          oscillator.disconnect(); gain.disconnect();
        }
        resolve(played);
      };
      // Suspended/closed output must never acknowledge a sound that did not finish.
      const timeout = setTimeout(() => finish(false), 3000);
      try {
        const start = context.currentTime;
        [880,1174.66].forEach((frequency,index) => {
          const oscillator=context.createOscillator(),gain=context.createGain(),at=start+index*0.12;
          nodes.push([oscillator, gain]);
          oscillator.type='sine';oscillator.frequency.setValueAtTime(frequency,at);
          gain.gain.setValueAtTime(0,at);gain.gain.linearRampToValueAtTime(0.045,at+0.012);
          gain.gain.exponentialRampToValueAtTime(0.0001,at+0.17);gain.gain.linearRampToValueAtTime(0,at+0.18);
          oscillator.connect(gain);gain.connect(context.destination);
          oscillator.onended=()=>{ if (++ended === 2) finish(context.state === 'running'); };
          oscillator.start(at);oscillator.stop(at+0.18);
        });
      } catch (_) { finish(false); }
    });
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
      // Sound is delivered independently by the durable global queue.
    };
    // Same-origin exclusive lock makes the durable claim atomic across tabs.
    if(navigator.locks)await navigator.locks.request(key,deliver);
    else if(document.hasFocus())deliver();
  }
  window.WorkbenchReturnFeedback={play,notify,canPlay:()=>Boolean(window.webkit?.messageHandlers?.workbenchReturnSound || context?.state === 'running')};
})();
