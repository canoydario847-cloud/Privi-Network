// Jose — language switching + example-conversation demo.
// Nothing here calls a real AI model; the "demo" is a small set of
// pre-written example exchanges, honestly labeled as such in every language.

const translations = {
  es: {
    "hero.kicker": "Un asistente pensado para quienes hacen negocios y vida diaria entre Sudamérica y China.",
    "hero.headline": "Hola, soy <span class=\"accent\">Jose</span>.",
    "hero.body": "Jose entiende español, portugués, chino e inglés, y ayuda a que una conversación en un idioma llegue completa al otro lado — en comercio, logística o una charla cualquiera.",
    "hero.cta_primary": "Ver un ejemplo",
    "hero.cta_ghost": "Leer más",
    "demo.label": "Ejemplo de conversación — no es una llamada en vivo a un modelo de IA.",
    "demo.picker.trade": "Comercio",
    "demo.picker.logistics": "Logística",
    "demo.picker.service": "Atención al cliente",
    "usecases.title": "Dónde ayuda Jose",
    "usecases.lede": "Cuatro situaciones concretas, no promesas abstractas.",
    "usecases.row1.name": "Comercio y aduanas",
    "usecases.row1.desc": "Lee documentos, facturas y certificados en chino o portugués, y explica lo importante en español.",
    "usecases.row2.name": "Logística y envíos",
    "usecases.row2.desc": "Traduce mensajes de proveedores y navieras sobre fechas, retrasos y cambios, sin perder los detalles que importan.",
    "usecases.row3.name": "Atención al cliente",
    "usecases.row3.desc": "Responde a clientes en su propio idioma, para que nadie tenga que esperar una traducción.",
    "usecases.row4.name": "Vida diaria",
    "usecases.row4.desc": "Ayuda a leer un menú, un contrato de alquiler o el mensaje de un amigo, sin traducir palabra por palabra.",
    "langsection.title": "Un mismo Jose, cuatro idiomas",
    "langsection.lede": "No es traducción automática genérica: Jose está pensado para el comercio y la vida entre estas dos regiones.",
    "steps.title": "Cómo funciona",
    "steps.lede": "Tres pasos, sin nada oculto en el medio.",
    "steps.s1.title": "Escribes en tu idioma",
    "steps.s1.desc": "En español, portugués, chino o inglés — el que uses normalmente.",
    "steps.s2.title": "Jose entiende el contexto",
    "steps.s2.desc": "No solo traduce palabras: distingue un documento de aduana de una charla informal.",
    "steps.s3.title": "Responde en el idioma correcto",
    "steps.s3.desc": "A ti, en el tuyo. A la otra persona, en el suyo — sin que nadie cambie de idioma.",
    "note.text": "Jose está en una etapa temprana. Esta página muestra ejemplos preparados para explicar la idea; todavía no es un chat en vivo conectado a un modelo de IA.",
    "footer.disclaimer": "Jose es un producto independiente. No está afiliado con Anthropic, con Claude, ni con ninguna otra empresa de inteligencia artificial.",
  },
  pt: {
    "hero.kicker": "Um assistente pensado para quem faz negócios e vive o dia a dia entre a América do Sul e a China.",
    "hero.headline": "Olá, eu sou <span class=\"accent\">Jose</span>.",
    "hero.body": "Jose entende português, espanhol, chinês e inglês, e ajuda uma conversa feita num idioma a chegar completa do outro lado — no comércio, na logística ou numa conversa qualquer.",
    "hero.cta_primary": "Ver um exemplo",
    "hero.cta_ghost": "Saiba mais",
    "demo.label": "Exemplo de conversa — não é uma chamada em tempo real a um modelo de IA.",
    "demo.picker.trade": "Comércio",
    "demo.picker.logistics": "Logística",
    "demo.picker.service": "Atendimento",
    "usecases.title": "Onde o Jose ajuda",
    "usecases.lede": "Quatro situações concretas, não promessas vagas.",
    "usecases.row1.name": "Comércio e alfândega",
    "usecases.row1.desc": "Lê documentos, notas fiscais e certificados em chinês ou espanhol, e explica o que importa em português.",
    "usecases.row2.name": "Logística e envios",
    "usecases.row2.desc": "Traduz mensagens de fornecedores e transportadoras sobre datas, atrasos e mudanças, sem perder os detalhes que contam.",
    "usecases.row3.name": "Atendimento ao cliente",
    "usecases.row3.desc": "Responde a clientes no idioma deles, para que ninguém precise esperar uma tradução.",
    "usecases.row4.name": "Vida do dia a dia",
    "usecases.row4.desc": "Ajuda a ler um cardápio, um contrato de aluguel ou a mensagem de um amigo, sem tradução palavra por palavra.",
    "langsection.title": "Um só Jose, quatro idiomas",
    "langsection.lede": "Não é tradução automática genérica: o Jose é pensado para o comércio e a vida entre essas duas regiões.",
    "steps.title": "Como funciona",
    "steps.lede": "Três passos, sem nada escondido no meio.",
    "steps.s1.title": "Você escreve no seu idioma",
    "steps.s1.desc": "Em português, espanhol, chinês ou inglês — o que você usa normalmente.",
    "steps.s2.title": "Jose entende o contexto",
    "steps.s2.desc": "Não traduz só palavras: distingue um documento alfandegário de uma conversa informal.",
    "steps.s3.title": "Responde no idioma certo",
    "steps.s3.desc": "Para você, no seu. Para a outra pessoa, no dela — sem que ninguém mude de idioma.",
    "note.text": "O Jose está em estágio inicial. Esta página mostra exemplos preparados para explicar a ideia; ainda não é um chat em tempo real conectado a um modelo de IA.",
    "footer.disclaimer": "Jose é um produto independente. Não tem relação com a Anthropic, com o Claude, nem com qualquer outra empresa de inteligência artificial.",
  },
  zh: {
    "hero.kicker": "专为在南美洲和中国之间做生意、过日子的人设计的助手。",
    "hero.headline": "你好，我是<span class=\"accent\">Jose</span>。",
    "hero.body": "Jose 懂西班牙语、葡萄牙语、中文和英语，能让一种语言里说的话完整地传到另一边——无论是做生意、处理物流，还是普通聊天。",
    "hero.cta_primary": "查看示例",
    "hero.cta_ghost": "了解更多",
    "demo.label": "对话示例——不是实时调用AI模型。",
    "demo.picker.trade": "贸易",
    "demo.picker.logistics": "物流",
    "demo.picker.service": "客户服务",
    "usecases.title": "Jose 能帮上忙的地方",
    "usecases.lede": "四个真实场景，不是空泛的承诺。",
    "usecases.row1.name": "贸易与海关",
    "usecases.row1.desc": "读懂西班牙语或葡萄牙语的文件、发票和证书，用中文说清楚重点。",
    "usecases.row2.name": "物流与发货",
    "usecases.row2.desc": "翻译供应商和货运公司关于日期、延误和变更的消息，不丢细节。",
    "usecases.row3.name": "客户服务",
    "usecases.row3.desc": "用客户自己的语言回复，不必等人翻译。",
    "usecases.row4.name": "日常生活",
    "usecases.row4.desc": "帮你看懂菜单、租房合同或朋友发来的消息，不是逐字硬翻。",
    "langsection.title": "同一个 Jose，四种语言",
    "langsection.lede": "不是通用机器翻译：Jose 是为这两个地区之间的生意和生活设计的。",
    "steps.title": "怎么用",
    "steps.lede": "三步，中间没有隐藏的部分。",
    "steps.s1.title": "用你自己的语言写",
    "steps.s1.desc": "中文、西班牙语、葡萄牙语或英语——你平时怎么说就怎么写。",
    "steps.s2.title": "Jose 理解上下文",
    "steps.s2.desc": "不只是翻译单词：能分清一份海关文件和一句随口的话。",
    "steps.s3.title": "用对的语言回复",
    "steps.s3.desc": "回你的时候用你的语言，回对方的时候用对方的语言——不用谁来回切换。",
    "note.text": "Jose 还在早期阶段。这个页面展示的是为了说明想法而准备的示例，还不是接入AI模型的实时聊天。",
    "footer.disclaimer": "Jose 是一个独立产品，与 Anthropic、Claude 或其他任何人工智能公司没有关联。",
  },
  en: {
    "hero.kicker": "An assistant built for people doing business and daily life between South America and China.",
    "hero.headline": "Hi, I'm <span class=\"accent\">Jose</span>.",
    "hero.body": "Jose understands Spanish, Portuguese, Chinese, and English, and helps a conversation that starts in one language arrive whole on the other side — in trade, logistics, or an ordinary chat.",
    "hero.cta_primary": "See an example",
    "hero.cta_ghost": "Read more",
    "demo.label": "Example conversation — not a live call to an AI model.",
    "demo.picker.trade": "Trade",
    "demo.picker.logistics": "Logistics",
    "demo.picker.service": "Customer service",
    "usecases.title": "Where Jose helps",
    "usecases.lede": "Four concrete situations, not vague promises.",
    "usecases.row1.name": "Trade and customs",
    "usecases.row1.desc": "Reads documents, invoices, and certificates in Chinese or Portuguese, and explains what matters in plain terms.",
    "usecases.row2.name": "Logistics and shipping",
    "usecases.row2.desc": "Translates messages from suppliers and carriers about dates, delays, and changes, without losing the details that count.",
    "usecases.row3.name": "Customer service",
    "usecases.row3.desc": "Replies to customers in their own language, so no one has to wait on a translation.",
    "usecases.row4.name": "Daily life",
    "usecases.row4.desc": "Helps read a menu, a lease, or a message from a friend, without word-for-word translation.",
    "langsection.title": "One Jose, four languages",
    "langsection.lede": "Not generic machine translation — Jose is built around trade and life between these two regions.",
    "steps.title": "How it works",
    "steps.lede": "Three steps, nothing hidden in between.",
    "steps.s1.title": "You write in your language",
    "steps.s1.desc": "Spanish, Portuguese, Chinese, or English — whichever you normally use.",
    "steps.s2.title": "Jose understands the context",
    "steps.s2.desc": "Not just word-for-word: it tells a customs document apart from a casual message.",
    "steps.s3.title": "It replies in the right language",
    "steps.s3.desc": "To you, in yours. To the other person, in theirs — without anyone switching.",
    "note.text": "Jose is early-stage. This page shows prepared examples to explain the idea; it isn't yet a live chat connected to an AI model.",
    "footer.disclaimer": "Jose is an independent product. It isn't affiliated with Anthropic, Claude, or any other AI company.",
  },
};

const demoScenarios = {
  es: {
    trade: [
      { who: "user", text: "¿Este documento de aduana chino dice que el envío pasó inspección?" },
      { who: "jose", text: "Sí. El sello dice “检验合格” — aprobado en inspección, sin observaciones.", tag: "Leído en chino" },
    ],
    logistics: [
      { who: "user", text: "El proveedor en Shenzhen escribió en chino sobre un retraso. ¿Qué dice?" },
      { who: "jose", text: "Dice que el contenedor sale el jueves en vez del martes, por un feriado local. No menciona costo adicional.", tag: "Leído en chino" },
    ],
    service: [
      { who: "user", text: "Un cliente en São Paulo escribió en portugués preguntando por su pedido." },
      { who: "jose", text: "Pregunta si el pedido #4521 ya salió de la bodega. Puedo responderle en portugués ahora mismo.", tag: "Leído en portugués" },
    ],
  },
  pt: {
    trade: [
      { who: "user", text: "Este documento alfandegário chinês diz que a carga passou na inspeção?" },
      { who: "jose", text: "Sim. O selo diz “检验合格” — aprovado na inspeção, sem observações.", tag: "Lido em chinês" },
    ],
    logistics: [
      { who: "user", text: "O fornecedor em Shenzhen escreveu em chinês sobre um atraso. O que diz?" },
      { who: "jose", text: "Diz que o contêiner sai na quinta em vez de terça, por um feriado local. Não menciona custo adicional.", tag: "Lido em chinês" },
    ],
    service: [
      { who: "user", text: "Um cliente em Buenos Aires escreveu em espanhol perguntando sobre o pedido." },
      { who: "jose", text: "Ele pergunta se o pedido #4521 já saiu do estoque. Posso responder em espanhol agora.", tag: "Lido em espanhol" },
    ],
  },
  zh: {
    trade: [
      { who: "user", text: "这份来自巴西供应商的葡萄牙语合同，有提到付款期限吗？" },
      { who: "jose", text: "有。合同写的是30天内付款，逾期按日加收0.5%的滞纳金。", tag: "原文为葡萄牙语" },
    ],
    logistics: [
      { who: "user", text: "智利的货运代理用西班牙语发来一条消息，说了什么？" },
      { who: "jose", text: "他说集装箱因为港口罢工延误到下周二，费用不变。", tag: "原文为西班牙语" },
    ],
    service: [
      { who: "user", text: "一位在布宜诺斯艾利斯的客户用西班牙语问订单情况。" },
      { who: "jose", text: "他问4521号订单是否已经发货。需要的话，我现在就能用西班牙语回复他。", tag: "原文为西班牙语" },
    ],
  },
  en: {
    trade: [
      { who: "user", text: "Does this Chinese customs document say the shipment passed inspection?" },
      { who: "jose", text: "Yes. The stamp reads “检验合格” — passed inspection, no issues noted.", tag: "Read in Chinese" },
    ],
    logistics: [
      { who: "user", text: "The supplier in Shenzhen wrote in Chinese about a delay. What does it say?" },
      { who: "jose", text: "It says the container leaves Thursday instead of Tuesday, because of a local holiday. No extra cost mentioned.", tag: "Read in Chinese" },
    ],
    service: [
      { who: "user", text: "A customer in São Paulo wrote in Portuguese asking about their order." },
      { who: "jose", text: "They're asking if order #4521 has shipped yet. I can reply in Portuguese right now.", tag: "Read in Portuguese" },
    ],
  },
};

let currentLang = "es";
let currentScenario = "trade";

function applyTranslations(lang) {
  const dict = translations[lang];
  document.documentElement.lang = lang;

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (dict[key] !== undefined) el.textContent = dict[key];
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    const key = el.getAttribute("data-i18n-html");
    if (dict[key] !== undefined) el.innerHTML = dict[key];
  });

  document.querySelector('[data-scenario="trade"]').textContent = dict["demo.picker.trade"];
  document.querySelector('[data-scenario="logistics"]').textContent = dict["demo.picker.logistics"];
  document.querySelector('[data-scenario="service"]').textContent = dict["demo.picker.service"];

  document.querySelectorAll(".lang-switch button").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-set-lang") === lang);
  });
}

function renderDemo(lang, scenario) {
  const thread = document.getElementById("demo-thread");
  thread.innerHTML = "";
  const turns = demoScenarios[lang][scenario];
  for (const turn of turns) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${turn.who}`;
    const textNode = document.createElement("span");
    textNode.textContent = turn.text;
    bubble.appendChild(textNode);
    if (turn.tag) {
      const tag = document.createElement("span");
      tag.className = "lang-tag";
      tag.textContent = turn.tag;
      bubble.appendChild(tag);
    }
    thread.appendChild(bubble);
  }
  document.querySelectorAll("#demo-picker button").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-scenario") === scenario);
  });
}

document.querySelectorAll(".lang-switch button").forEach((btn) => {
  btn.addEventListener("click", () => {
    currentLang = btn.getAttribute("data-set-lang");
    applyTranslations(currentLang);
    renderDemo(currentLang, currentScenario);
  });
});

document.querySelectorAll("#demo-picker button").forEach((btn) => {
  btn.addEventListener("click", () => {
    currentScenario = btn.getAttribute("data-scenario");
    renderDemo(currentLang, currentScenario);
  });
});

applyTranslations(currentLang);
renderDemo(currentLang, currentScenario);
