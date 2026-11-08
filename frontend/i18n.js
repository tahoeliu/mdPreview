/* 前端和原生菜单读取同一 JSON；界面语言与文档排版语言分离。 */
window.I18n=(()=>{
 let locale='en',dictionary={};
 function normalize(value){const lang=String(value||'en').replace(/_/g,'-').toLowerCase();if(/^zh-(hant|tw|hk|mo)/.test(lang))return 'zh-Hant';if(lang.startsWith('zh'))return 'zh-Hans';const base=lang.split('-')[0];return ['ja','ko','de','fr','es'].includes(base)?base:'en';}
 function configure(data){locale=normalize(data.locale);dictionary=data.messages||{};}
 function translate(en,zh){return dictionary[en]??(locale==='zh-Hans'?zh:en);}
 async function load(){if(!Bridge.ready()||!window.pywebview.api.get_i18n)return;const data=await Bridge.call('get_i18n');configure(data);}
 return {normalize,configure,load,t:translate,get locale(){return locale;}};
})();
