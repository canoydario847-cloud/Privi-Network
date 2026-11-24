import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../jose-site/',import.meta.url));
const read=(name)=>readFileSync(path.join(root,name),'utf8');
const domain='https://jose-site-21hs.onrender.com';
const pages=[
  ['index.html','en','/'],
  ['discover.html','en','/discover.html'],
  ['es/index.html','es','/es/'],
  ['pt/index.html','pt','/pt/'],
  ['fr/index.html','fr','/fr/'],
  ['hi/index.html','hi','/hi/']
];
test('all Hey Jose international pages have canonical metadata and crawlable content',()=>{
 for(const [file,lang,url] of pages){
  const html=read(file);
  assert.match(html,new RegExp('<html lang="'+lang+'">'),file);
  assert.match(html,/<meta name="description" content="[^"]{40,}"/,file);
  assert.ok(html.includes('<link rel="canonical" href="'+domain+url+'">'),file);
  assert.match(html,/<h1>[^<]{10,}<\/h1>/,file);
  assert.match(html,/jose-backend-075d\.onrender\.com\/chat\.html/,file);
  assert.ok(html.includes('Privi'),file);
 }
});
test('the public homepage keeps real Hey Jose chat and links to every language',()=>{
 const html=read('index.html');
 assert.match(html,/<iframe id="hey-jose"/);
 assert.match(html,/<main class="info">/);
 for(const url of ['/discover.html','/es/','/pt/','/fr/','/hi/','/share.html'])
  assert.ok(html.includes('href="'+url+'"'),url);
 assert.doesNotMatch(html,/official OpenAI partner|official ChatGPT partner/i);
});
test('robots, sitemap, and share pages are present and internally consistent',()=>{
 const robots=read('robots.txt'),sitemap=read('sitemap.xml'),share=read('share.html');
 assert.match(robots,/User-agent: \*/);
 assert.match(robots,/sitemap\.xml/);
 for(const [, ,url] of pages)assert.ok(sitemap.includes('<loc>'+domain+url+'</loc>'),url);
 assert.ok(sitemap.includes('<loc>'+domain+'/share.html</loc>'));
 assert.match(share,/facebook\.com\/sharer\/sharer\.php/);
 assert.match(share,/linkedin\.com\/sharing\/share-offsite/);
 assert.match(share,/twitter\.com\/intent\/tweet/);
 assert.match(share,/TEST/);
 assert.match(share,/OAuth/);
 assert.equal(existsSync(path.join(root,'share.html')),true);
});
