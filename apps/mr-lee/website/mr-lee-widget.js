/* Mr. Lee website widget, FUTURE Privi website integration only.
   This browser script never holds an OpenAI key, chain key or gateway token.
   It calls a SAME-ORIGIN, authenticated Privi website backend proxy. */
(function () {
  "use strict";
  class MrLeeWidget extends HTMLElement {
    connectedCallback() {
      if (this.shadowRoot) return;
      const root = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = `
        :host{display:block;color:#e5edf8;font:15px system-ui,sans-serif;max-width:580px}
        .shell{border:1px solid #3c4c67;background:#121b2a;border-radius:18px;padding:20px;box-shadow:0 18px 36px #080d18a6}
        h2{font-size:22px;margin:0 0 5px;font-weight:750} .subtitle{margin:0 0 16px;color:#a9b8d0}
        .chat{height:280px;overflow:auto;background:#0c1420;border:1px solid #25334b;padding:12px;border-radius:12px;margin-bottom:14px}
        .bubble{white-space:pre-wrap;word-break:break-word;margin:10px 0;padding:11px;border-radius:12px;line-height:1.5;background:#273349}
        .mine{background:#193c43} label{display:block;margin:10px 0 6px;font-size:13px;color:#c8d5e8}
        select,textarea,button{font:inherit;border-radius:10px;box-sizing:border-box}
        select,textarea{display:block;background:#0c1420;color:#fff;border:1px solid #485d77;width:100%;padding:10px}
        textarea{min-height:92px;resize:vertical} button{background:#59d7a7;border:0;color:#09251e;padding:11px 16px;font-weight:750;cursor:pointer;margin-top:10px}
        button:disabled{opacity:.6;cursor:not-allowed}.notice{font-size:12px;color:#a9b8d0;margin-top:14px}
        .error{color:#ffb9b9}.status{min-height:18px;font-size:13px;line-height:1.4}
      `;
      const shell = document.createElement("section"); shell.className = "shell";
      const heading = document.createElement("h2"); heading.textContent = "Mr. Lee — Privi AI";
      const sub = document.createElement("p"); sub.className = "subtitle";
      sub.textContent = "Privi network utilities • Wallet help • Paper-trade analysis";
      const chat = document.createElement("div");
      chat.className = "chat"; chat.setAttribute("role", "log");
      chat.setAttribute("aria-live", "polite");
      const intro = document.createElement("div"); intro.className = "bubble";
      intro.textContent = "Welcome. I can help with Privi utilities, network questions and simulated trading scenarios. I cannot move funds or place orders.";
      chat.append(intro);
      const form = document.createElement("form");
      const label = document.createElement("label"); label.textContent = "Topic";
      const select = document.createElement("select"); select.setAttribute("aria-label","Topic");
      for (const [value,title] of [["utility","Privi utilities"],["network","Network status"],["markets","Trading education"],["support","Help"]]) {
        const option = document.createElement("option"); option.value = value; option.textContent = title;
        select.append(option);
      }
      const messageLabel = document.createElement("label"); messageLabel.textContent = "Ask Mr. Lee";
      const box = document.createElement("textarea"); box.maxLength = 1500; box.required = true;
      box.placeholder = "How do Privi transactions, staking or network utilities work?";
      box.setAttribute("aria-label", "Question");
      const btn = document.createElement("button"); btn.type = "submit"; btn.textContent = "Ask Mr. Lee";
      const status = document.createElement("p"); status.className = "status"; status.setAttribute("role", "status");
      const notice = document.createElement("p"); notice.className = "notice";
      notice.textContent = "Trading features are educational simulations only. Never share private keys. Mr. Lee activates only after the Privi website and approved network are verified.";
      const bubble = (text, mine = false) => {
        const item = document.createElement("div"); item.className = mine ? "bubble mine" : "bubble";
        item.textContent = text; chat.append(item); chat.scrollTop = chat.scrollHeight;
      };
      form.append(label, select, messageLabel, box, btn);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = box.value.trim();
        if (!message) return;
        // Website must render a CSRF token bound to the authenticated session.
        // This is NOT an OpenAI key, private chain key, or backend HMAC secret.
        const csrfToken = this.getAttribute("csrf-token");
        if (!csrfToken || csrfToken.length < 16 || csrfToken.length > 256) {
          status.className = "status error";
          status.textContent = "Privi secure session setup is required before chat can activate.";
          return;
        }
        btn.disabled = true; status.textContent = "Checking Privi and contacting Mr. Lee…";
        bubble(message, true); box.value = "";
        try {
          const response = await fetch("/api/mr-lee/chat", {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
            body: JSON.stringify({ category: select.value, message })
          });
          if (!response.ok) {
            status.className = "status error";
            status.textContent = response.status === 503
              ? "Mr. Lee is not yet activated on the verified Privi network."
              : "Mr. Lee is unavailable or your Privi website session needs renewal.";
            return;
          }
          const body = await response.json();
          if (!body || typeof body.reply !== "string") throw Error("Invalid response");
          bubble(body.reply);
          status.className = "status"; status.textContent = "Read-only Privi assistant";
        } catch {
          status.className = "status error";
          status.textContent = "Unable to connect. Try again after the website integration is active.";
        } finally {
          btn.disabled = false;
        }
      });
      shell.append(heading,sub,chat,form,status,notice);
      root.append(style,shell);
    }
  }
  if (!customElements.get("mr-lee-privi")) customElements.define("mr-lee-privi", MrLeeWidget);
})();
