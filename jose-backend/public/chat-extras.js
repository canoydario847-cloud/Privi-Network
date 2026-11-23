// Hey Jose browser attachment UX. Attachments are sent only with the chosen prompt.
// No file/image is stored in localStorage, chat exports, or external databases by this module.
(() => {
  const $=id=>document.getElementById(id);
  const input=$('attachmentFile');
  const notice=$('attachmentStatus');
  let attachment=null;
  let lastReply='';
  const defaultNotice='Images (PNG/JPEG/WebP) or small text/code files are supported. PDFs and video are not yet supported.';
  function clearAttachment(){
    attachment=null;
    input.value='';
    $('clearAttachment').hidden=true;
    notice.textContent=defaultNotice;
  }
  function fail(error){
    clearAttachment();
    notice.textContent='Attachment not ready: '+(error?.message||'Invalid file.');
  }
  async function prepareImage(file){
    if(file.size>5000000)throw new Error('Choose an image smaller than 5 MB.');
    const bitmap=await createImageBitmap(file);
    const scale=Math.min(1,1024/Math.max(bitmap.width,bitmap.height));
    const canvas=document.createElement('canvas');
    canvas.width=Math.max(1,Math.round(bitmap.width*scale));
    canvas.height=Math.max(1,Math.round(bitmap.height*scale));
    const ctx=canvas.getContext('2d');
    if(!ctx)throw new Error('The browser cannot resize this image.');
    ctx.fillStyle='#fff';
    ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
    bitmap.close?.();
    const dataUrl=canvas.toDataURL('image/jpeg',0.78);
    if(dataUrl.length>1600000)throw new Error('Image is still too large after compression.');
    return {kind:'image',name:file.name,dataUrl};
  }
  async function prepareText(file){
    if(!/\.(txt|md|csv|json|js|ts|py|html|css|sol|xml|ya?ml|log|sql)$/i.test(file.name)) {
      throw new Error('Unsupported file type. Convert to plain text, code, CSV, JSON or Markdown.');
    }
    if(file.size>50000)throw new Error('Text files must be smaller than 50 KB.');
    const content=await file.text();
    if(!content||content.length>12000)throw new Error('Text file must contain 1–12,000 characters.');
    return {kind:'text',name:file.name,content};
  }
  $('attach').addEventListener('click',()=>input.click());
  $('clearAttachment').addEventListener('click',clearAttachment);
  input.addEventListener('change',async()=>{
    const file=input.files?.[0];
    if(!file)return;
    notice.textContent='Preparing '+file.name+'…';
    try {
      const supported=['image/png','image/jpeg','image/webp'];
      attachment=supported.includes(file.type)?await prepareImage(file):await prepareText(file);
      $('clearAttachment').hidden=false;
      notice.textContent='Ready: '+file.name+' ('+attachment.kind+'). Sent only when you submit your next message.';
    }catch(error){fail(error);}
  });
  $('newChat').addEventListener('click',()=>{
    window.joseResetChat?.();
    clearAttachment();
    lastReply='';
    $('status').textContent='New conversation started in this tab. Previous messages have been cleared.';
  });
  $('exportChat').addEventListener('click',()=>{
    const payload=JSON.stringify({format:'hey-jose-chat-v1',exportedAt:new Date().toISOString(),messages:window.joseChatHistory||[]},null,2);
    const url=URL.createObjectURL(new Blob([payload],{type:'application/json'}));
    const link=document.createElement('a');
    link.href=url;link.download='hey-jose-conversation.json';
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    $('status').textContent='Conversation exported. Images and text attachments are not included.';
  });
  $('copyReply').addEventListener('click',async()=>{
    if(!lastReply){$('status').textContent='No reply available to copy yet.';return;}
    try{
      await navigator.clipboard.writeText(lastReply);
      $('status').textContent='Last reply copied to clipboard.';
    }catch{
      $('status').textContent='Clipboard not available; select and copy the text directly.';
    }
  });
  window.joseAddons={
    getAttachment:()=>attachment,
    getLastReply:()=>lastReply,
    onSent:(reply)=>{lastReply=reply;clearAttachment();}
  };
})();
