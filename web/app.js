"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function weatherIcon(text = "") {
  if (/雷/.test(text)) return "⛈️";
  if (/雪/.test(text)) return "❄️";
  if (/雨/.test(text)) return "🌧️";
  if (/雾|霾/.test(text)) return "🌫️";
  if (/阴/.test(text)) return "☁️";
  if (/云/.test(text)) return "⛅";
  if (/晴/.test(text)) return "☀️";
  return "🌤️";
}

function renderWeather(w) {
  $("#weather-note").textContent = w.note || "";
  $("#weather").innerHTML = (w.cards || []).map((c) => `
    <div class="weather-card">
      <div class="date">${esc(c.date.slice(5).replace("-", "月"))}日 ${esc(c.week)}</div>
      <div class="icon">${weatherIcon(c.dayweather)}</div>
      <div class="temp">${esc(c.nighttemp)}° ~ ${esc(c.daytemp)}°</div>
      <div class="desc">白天 ${esc(c.dayweather)} · 夜间 ${esc(c.nightweather)}</div>
      <div class="wind">${esc(c.wind)}</div>
      <div class="kind">${esc(c.kind)}</div>
    </div>`).join("");
  const live = w.live || [];
  $("#live-weather").innerHTML = live.length
    ? `<span class="muted" style="margin:0;align-self:center">高德实时预报：</span>` +
      live.map((f) => `<span class="chip">${esc(f.date.slice(5))} ${weatherIcon(f.dayweather)} ${esc(f.dayweather)} ${esc(f.nighttemp)}~${esc(f.daytemp)}°C</span>`).join("")
    : "";
}

function spotImage(s, label, color) {
  const lab = `<span class="label" style="background:${color}">${label}</span>`;
  if (s.photos && s.photos.length) {
    return `<div class="spot-img" data-full="${esc(s.photos[0])}" style="background-image:url('${esc(s.photos[0])}')">${lab}</div>`;
  }
  return `<div class="spot-img placeholder" style="background:linear-gradient(135deg, ${color}, #1e6091)">${lab}${esc(s.name)}</div>`;
}

function renderDay(d, hasKey) {
  const legend = d.spots.map((s, i) => `<span><b style="background:${d.color}">${String.fromCharCode(65 + i)}</b>${esc(s.name)}</span>`).join("");
  const timeline = d.schedule.map((item, i) => {
    let extra = "";
    if (item.type === "taxi") {
      const leg = d.legs[d.schedule.slice(0, i).filter((x) => x.type === "taxi").length];
      if (leg) extra = ` <a href="${esc(leg.nav_url)}" target="_blank" rel="noopener">高德打车/导航 ↗</a>${leg.estimated ? ' <span class="muted">(估算)</span>' : ""}`;
    }
    const icon = { spot: "📍", taxi: "🚕", meal: "🍜" }[item.type] || "";
    return `<li><span class="time">${esc(item.time)}</span><span class="${item.type}">${icon} ${esc(item.text)}${extra}</span></li>`;
  }).join("");

  const cards = d.spots.map((s, i) => `
    <article class="spot-card">
      ${spotImage(s, String.fromCharCode(65 + i), d.color)}
      <div class="spot-body">
        <h3>${esc(s.name)}</h3>
        <div class="row">🕘 ${esc(s.arrive)} - ${esc(s.leave)}（建议游玩 ${esc(s.stay)} 小时）</div>
        ${s.rating ? `<div class="rating">★ ${esc(s.rating)}</div>` : ""}
        <div class="intro">${esc(s.intro)}</div>
        <div class="row">🎫 ${esc(s.ticket)}</div>
        ${s.opentime ? `<div class="row">⏰ ${esc(s.opentime)}</div>` : ""}
        ${s.address ? `<div class="row">📌 ${esc(s.address)}</div>` : ""}
      </div>
    </article>`).join("");

  const map = hasKey
    ? `<img alt="第${d.index}天路线图" data-day="${d.index}" src="/api/map?day=${d.index}" draggable="false">`
    : `<div class="map-empty">配置高德 Key 后，这里显示高德地图绘制的当天打车路线<br>（见 README：在 .env 中填写 AMAP_MAPS_API_KEY）</div>`;

  return `
  <section class="day" id="day-${d.index}">
    <div class="day-head">
      <span class="day-badge" style="background:${d.color}">DAY ${d.index}</span>
      <h2>${esc(d.theme)}</h2>
      <span class="meta">${esc(d.date)} ${esc(d.week)} · ${d.spots.length} 个景点 · 景点间打车</span>
    </div>
    <div class="day-body">
      <div>
        <div class="map-box" data-day="${d.index}">
          ${map}
          ${hasKey ? `<div class="map-ctrl"><button data-z="+1" title="放大">+</button><button data-z="-1" title="缩小">−</button><button data-z="0" title="自适应">⤢</button></div><span class="map-zoom">自适应视野</span>` : ""}
        </div>
        <div class="legend">${legend}<span style="color:${d.color}">━ 打车路线</span></div>
      </div>
      <div>
        <ul class="timeline">${timeline}</ul>
        <div class="taxi-total">当日打车合计约 ${esc(d.taxi_total)} 元</div>
      </div>
    </div>
    <div class="spots">${cards}</div>
  </section>`;
}

/* 地图缩放：通过后端代理请求不同 zoom 的高德静态地图 */
function bindMaps() {
  document.querySelectorAll(".map-box[data-day]").forEach((box) => {
    const img = $("img", box);
    if (!img) return;
    let zoom = null;
    const label = $(".map-zoom", box);
    const load = () => {
      img.classList.add("map-loading");
      img.src = `/api/map?day=${box.dataset.day}${zoom ? `&zoom=${zoom}` : ""}`;
      label.textContent = zoom ? `缩放级别 ${zoom}` : "自适应视野";
    };
    img.addEventListener("load", () => img.classList.remove("map-loading"));
    img.addEventListener("error", () => {
      img.remove();
      box.insertAdjacentHTML("afterbegin", `<div class="map-empty">高德地图加载失败，请检查 Key 是否为「Web服务」类型且未超出配额</div>`);
    });
    const change = (dz) => {
      if (dz === 0) zoom = null; else zoom = Math.max(3, Math.min(17, (zoom || 13) + dz));
      load();
    };
    box.querySelectorAll("button[data-z]").forEach((b) => b.addEventListener("click", () => change(Number(b.dataset.z))));
    let wheelLock = false;
    box.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (wheelLock) return;
      wheelLock = true;
      setTimeout(() => (wheelLock = false), 350);
      change(e.deltaY < 0 ? 1 : -1);
    }, { passive: false });
  });
}

function bindLightbox() {
  const lb = $("#lightbox");
  document.addEventListener("click", (e) => {
    const el = e.target.closest(".spot-img[data-full]");
    if (el) { $("img", lb).src = el.dataset.full; lb.hidden = false; }
    else if (e.target.closest("#lightbox")) lb.hidden = true;
  });
}

async function main() {
  const plan = await fetch("/api/plan").then((r) => r.json());
  document.title = plan.title;
  $("#title").textContent = plan.title;
  $("#subtitle").textContent = `${plan.start_date} 至 ${plan.end_date} · 每天 3 个景点 · 同日景点之间打车前往`;
  $("#day-nav").innerHTML = plan.days.map((d) => `<a href="#day-${d.index}">第 ${d.index} 天 · ${esc(d.theme.split(" · ")[0])}</a>`).join("");

  if (plan.source !== "mcp") {
    const b = $("#banner");
    b.hidden = false;
    b.textContent = "当前为内置示例数据。在项目根目录的 .env 中填写高德 Key（AMAP_MAPS_API_KEY）后重新运行，即可通过高德 MCP 获取实时天气、景点信息、照片与打车路线。";
  }
  renderWeather(plan.weather);
  $("#tips").innerHTML = plan.tips.map((t) => `<li>${esc(t)}</li>`).join("");
  $("#days").innerHTML = plan.days.map((d) => renderDay(d, plan.has_key)).join("");
  if (plan.personal_map_url) {
    $("#overview-map-section").hidden = false;
    $("#personal-map").href = plan.personal_map_url;
  }
  $("#footer-source").textContent = plan.source === "mcp"
    ? `数据来源：高德地图 MCP Server（${plan.mcp_tools_used.join("、")}）· 生成于 ${plan.generated_at}`
    : `数据来源：内置示例数据 · 生成于 ${plan.generated_at}`;
  bindMaps();
  bindLightbox();
}

main().catch((e) => {
  $("#subtitle").textContent = "加载失败：" + e.message;
});
