// Hey Jose Gmail: least-permissive scopes required for reading and sending.
// Note gmail.readonly is a Google restricted scope and public use may require
// verification/security review. Never request Google passwords or Gmail tokens.
import { postForm } from '../http-client.js';

export const GMAIL_SCOPES=Object.freeze([
  'https://www.googleapis.com/auth/gmail.readonly',
  'https://www.googleapis.com/auth/gmail.send'
]);
export const google={
  id:'google',
  name:'Gmail (read and send)',
  setup:{
    registerUrl:'https://console.cloud.google.com/apis/credentials',
    envVars:[
      {key:'GOOGLE_CLIENT_ID',label:'Google OAuth web client ID'},
      {key:'GOOGLE_CLIENT_SECRET',label:'Google OAuth web client secret'},
      {key:'APP_SECRET',label:'Hey Jose server encryption secret (32+ characters)'}
    ],
    steps:[
      'Enable Gmail API in Google Cloud and configure OAuth consent, data-use policy, and only required Gmail scopes.',
      'Create a Google OAuth 2.0 Web application and add https://jose-backend-075d.onrender.com/callback/google to authorized redirect URIs.',
      'Configure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and APP_SECRET in Jose backend Render environment.',
      'Publish only after any required Google verification and security assessment. Users grant their own Gmail permissions and can disconnect.'
    ]
  },
  isConfigured(){return Boolean(process.env.GOOGLE_CLIENT_ID&&process.env.GOOGLE_CLIENT_SECRET&&(process.env.APP_SECRET||'').length>=32);},
  missingEnvVars(){
    return ['GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET',...((process.env.APP_SECRET||'').length>=32?[]:['APP_SECRET'])].filter(k=>!process.env[k]||(k==='APP_SECRET'&&process.env[k].length<32));
  },
  buildAuthorizeUrl(state,redirectUri){
    const p=new URLSearchParams({
      client_id:process.env.GOOGLE_CLIENT_ID,
      redirect_uri:redirectUri,response_type:'code',
      scope:GMAIL_SCOPES.join(' '),
      access_type:'offline',prompt:'consent',state
    });
    return 'https://accounts.google.com/o/oauth2/v2/auth?'+p.toString();
  },
  async exchangeCode(code,redirectUri){
    const {status,body}=await postForm('https://oauth2.googleapis.com/token',{
      client_id:process.env.GOOGLE_CLIENT_ID,client_secret:process.env.GOOGLE_CLIENT_SECRET,
      redirect_uri:redirectUri,grant_type:'authorization_code',code
    });
    if(status!==200||!body?.access_token)throw Error('Google OAuth token exchange failed; restart Gmail connection.');
    const granted=String(body.scope||'').split(/\s+/).filter(Boolean);
    if(!GMAIL_SCOPES.every(s=>granted.includes(s)))throw Error('The Google authorization did not grant both Gmail read and send permissions.');
    return {
      accessToken:body.access_token,
      refreshToken:body.refresh_token||null,
      expiresInSeconds:Number(body.expires_in)||3600,
      scopes:granted
    };
  }
};
