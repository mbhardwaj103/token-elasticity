/* Token Elasticity dashboard: renders dashboard/data/dashboard.json with ECharts. */
(() => {
  "use strict";

  const state = { data: null, range: 0, charts: {} };
  const $ = (sel) => document.querySelector(sel);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const SERIES = () => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => css(`--s${i}`));

  // ---------- formatting ----------
  const isNum = (v) => typeof v === "number" && Number.isFinite(v);
  const compact = (v, digits = 1) => {
    if (!isNum(v)) return "–";
    const a = Math.abs(v);
    const units = [[1e15, "Q"], [1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];
    for (const [n, u] of units) if (a >= n) return (v / n).toFixed(digits) + u;
    return v.toFixed(digits);
  };
  const pct = (v, d = 1) => (isNum(v) ? v.toFixed(d) + "%" : "–");
  const signed = (v, d = 1, suffix = "%") => (isNum(v) ? (v > 0 ? "+" : "") + v.toFixed(d) + suffix : "–");
  const usd = (v) => (isNum(v) ? "$" + (v >= 100 ? v.toFixed(0) : v >= 1 ? v.toFixed(2) : v.toFixed(3)) : "–");
  const fmtDate = (s) => new Date(s + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

  // ---------- shared chart chrome ----------
  function baseOption() {
    const ink2 = css("--ink-2"), muted = css("--muted"), grid = css("--grid"), axis = css("--axis"), surface = css("--surface");
    return {
      animationDuration: 300,
      textStyle: { fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: ink2 },
      grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 14, itemHeight: 3, textStyle: { color: ink2, fontSize: 12 }, type: "scroll" },
      tooltip: {
        trigger: "axis",
        backgroundColor: surface,
        borderColor: css("--border") || axis,
        textStyle: { color: css("--ink"), fontSize: 12 },
        axisPointer: { type: "line", lineStyle: { color: axis, width: 1 } },
        confine: true,
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: axis } },
        axisTick: { show: false },
        axisLabel: { color: muted, fontSize: 11, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        axisLabel: { color: muted, fontSize: 11 },
        splitLine: { lineStyle: { color: grid, width: 1 } },
      },
    };
  }

  const line = (name, points, color, extra = {}) => ({
    name, type: "line", data: points, showSymbol: false, symbolSize: 8, connectNulls: true,
    lineStyle: { width: 2, color, cap: "round", join: "round", ...(extra.lineStyle || {}) },
    itemStyle: { color, borderColor: css("--surface"), borderWidth: 2 },
    emphasis: { focus: "series" },
    ...extra,
    lineStyle: { width: 2, color, cap: "round", join: "round", ...(extra.lineStyle || {}) },
  });

  // Label only the final point of a series (selective direct label).
  const endLabel = (fmt) => ({ show: true, formatter: (p) => (isNum(p.value?.[1]) ? fmt(p.value[1]) : ""), color: css("--ink-2"), fontSize: 11, distance: 6 });

  function tooltipFormatter(valueFmt) {
    return (params) => {
      const list = Array.isArray(params) ? params : [params];
      if (!list.length) return "";
      const date = list[0].value ? fmtDate(String(list[0].value[0]).slice(0, 10)) : list[0].axisValueLabel;
      const rows = list
        .filter((p) => p.value && isNum(p.value[1]))
        .map((p) => {
          const key = `<span style="display:inline-block;width:12px;height:2px;background:${p.color};vertical-align:middle;margin-right:6px"></span>`;
          return `<div style="display:flex;justify-content:space-between;gap:16px"><span>${key}<span style="color:${css("--ink-2")}">${escapeHtml(p.seriesName)}</span></span><strong>${valueFmt(p.value[1], p.seriesName)}</strong></div>`;
        });
      return `<div style="margin-bottom:4px;color:${css("--muted")}">${date}</div>${rows.join("")}`;
    };
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function chart(id) {
    const el = document.getElementById(id);
    if (!state.charts[id]) state.charts[id] = echarts.init(el, null, { renderer: "svg" });
    return state.charts[id];
  }

  function emptyChart(id, msg) {
    const c = chart(id);
    c.clear();
    c.setOption({ title: { text: msg, left: "center", top: "middle", textStyle: { color: css("--muted"), fontSize: 13, fontWeight: 400 } } });
  }

  // Table view twin for every chart (tooltips never gate values).
  function tableView(id, headers, rows) {
    const card = document.getElementById(id).closest(".card");
    let det = card.querySelector("details.table");
    if (!det) {
      det = document.createElement("details");
      det.className = "table";
      det.innerHTML = "<summary>Show data table</summary><div class='tablewrap'><table><thead></thead><tbody></tbody></table></div>";
      card.appendChild(det);
    }
    const thead = det.querySelector("thead"), tbody = det.querySelector("tbody");
    thead.replaceChildren();
    tbody.replaceChildren();
    const htr = document.createElement("tr");
    headers.forEach((h) => { const th = document.createElement("th"); th.textContent = h; htr.appendChild(th); });
    thead.appendChild(htr);
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      r.forEach((c) => { const td = document.createElement("td"); td.textContent = c; tr.appendChild(td); });
      tbody.appendChild(tr);
    });
  }

  // ---------- data helpers ----------
  function weekly() {
    const w = state.data?.tokens?.weekly;
    if (!w || !w.week?.length) return null;
    const start = state.range ? Math.max(0, w.week.length - state.range) : 0;
    const out = {};
    for (const k of Object.keys(w)) out[k] = w[k].slice(start);
    return out;
  }
  // Drop missing points instead of emitting nulls: end labels and log axes break on null values.
  const pairs = (xs, ys) => xs.map((x, i) => [x, ys?.[i]]).filter(([, v]) => isNum(v));
  const reindex = (ys) => {
    const first = ys.find(isNum);
    return ys.map((v) => (isNum(v) && first ? (v / first) * 100 : null));
  };
  const pts = (arr) => (arr || []).map((p) => [p.date, p.value]);
  const cutoffDate = () => {
    const w = weekly();
    return state.range && w ? w.week[0] : null;
  };

  // ---------- KPI tiles ----------
  function renderKpis() {
    const k = state.data.kpis || {};
    const tiles = [
      {
        label: "Weekly tokens (OpenRouter)",
        value: compact(k.weekly_tokens),
        delta: isNum(k.tokens_growth_4w_pct) ? [signed(k.tokens_growth_4w_pct), "vs 4 weeks earlier", k.tokens_growth_4w_pct >= 0] : null,
        foot: isNum(k.tokens_change_since_start_x) ? `${k.tokens_change_since_start_x.toFixed(1)}× since first week` : "",
      },
      {
        label: "Average price per 1M tokens",
        value: usd(k.effective_price),
        delta: isNum(k.price_change_since_start_pct) ? [signed(k.price_change_since_start_pct, 0), "since first week", null] : null,
        foot: isNum(k.price_coverage) ? `priced models = ${pct(k.price_coverage * 100, 0)} of tokens` : "",
      },
      {
        label: "Implied weekly spend",
        value: isNum(k.spend_usd_week) ? "$" + compact(k.spend_usd_week) : "–",
        foot: "tokens × average price, priced models only",
      },
      {
        label: "Price elasticity (12-week)",
        value: isNum(k.elasticity) ? k.elasticity.toFixed(2) : "–",
        foot: !isNum(k.elasticity) ? ""
          : k.elasticity < -1 ? "elastic: cheaper tokens grow spend"
          : Math.abs(k.elasticity) < 0.2 ? "≈ 0: volume growing regardless of price"
          : k.elasticity < 0 ? "inelastic: volume responds less than price"
          : "volume and price rising together",
      },
      {
        label: "World AI user share",
        value: pct(k.global_adoption),
        delta: isNum(k.global_adoption_change_pp) ? [signed(k.global_adoption_change_pp, 1, " pp"), "vs prior report", k.global_adoption_change_pp >= 0] : null,
        foot: "% of people aged 15–64",
      },
      {
        label: "US businesses using AI",
        value: pct(k.us_business_adoption),
        delta: isNum(k.us_business_change_6m_pp) ? [signed(k.us_business_change_6m_pp, 1, " pp"), "vs ~6 months earlier", k.us_business_change_6m_pp >= 0] : null,
        foot: k.us_business_adoption_date ? `period ending ${fmtDate(k.us_business_adoption_date)}` : "",
      },
    ];
    const root = $("#kpis");
    root.replaceChildren();
    for (const t of tiles) {
      const div = document.createElement("div");
      div.className = "tile";
      const label = document.createElement("div"); label.className = "label"; label.textContent = t.label;
      const value = document.createElement("div"); value.className = "value"; value.textContent = t.value;
      div.append(label, value);
      if (t.delta || t.foot) {
        const d = document.createElement("div"); d.className = "delta";
        if (t.delta) {
          const [txt, ctx, good] = t.delta;
          const s = document.createElement("span");
          if (good !== null) s.className = good ? "up" : "down";
          s.textContent = (good === null ? "" : good ? "▲ " : "▼ ") + txt;
          d.append(s, document.createTextNode(" " + ctx + (t.foot ? " · " : "")));
        }
        if (t.foot) d.append(document.createTextNode(t.foot));
        div.appendChild(d);
      }
      root.appendChild(div);
    }
  }

  // ---------- charts ----------
  function renderIndex() {
    const w = weekly();
    if (!w || !w.effective_price) return emptyChart("c-index", "No token/price data yet — click Refresh");
    const [c1, c2, c3] = SERIES();
    const vol = reindex(w.tokens), price = reindex(w.effective_price), spend = reindex(w.spend_usd);
    const opt = baseOption();
    opt.yAxis = { ...opt.yAxis, type: "log", logBase: 10, axisLabel: { ...opt.yAxis.axisLabel, formatter: (v) => compact(v, 0) } };
    opt.tooltip.formatter = tooltipFormatter((v) => v.toFixed(0));
    opt.series = [
      line("Token volume", pairs(w.week, vol), c1, { endLabel: endLabel((v) => v.toFixed(0)) }),
      line("Average price", pairs(w.week, price), c2, { endLabel: endLabel((v) => v.toFixed(0)) }),
      line("Implied spend", pairs(w.week, spend), c3, { endLabel: endLabel((v) => v.toFixed(0)) }),
    ];
    opt.grid.right = 40;
    chart("c-index").setOption(opt, true);
    tableView("c-index", ["Week", "Tokens", "Avg $/1M", "Spend $", "Volume idx", "Price idx", "Spend idx"],
      w.week.map((d, i) => [d, compact(w.tokens[i]), usd(w.effective_price[i]), compact(w.spend_usd[i]), vol[i]?.toFixed(0) ?? "–", price[i]?.toFixed(0) ?? "–", spend[i]?.toFixed(0) ?? "–"]).reverse());
  }

  function renderElasticity() {
    const w = weekly();
    if (!w || !w.elasticity_rolling) return emptyChart("c-elasticity", "Needs price data");
    const [c1] = SERIES();
    const opt = baseOption();
    opt.legend.show = false;
    opt.tooltip.formatter = tooltipFormatter((v) => v.toFixed(2));
    const muted = css("--muted");
    opt.series = [
      line("Rolling elasticity", pairs(w.week, w.elasticity_rolling), c1, {
        endLabel: endLabel((v) => v.toFixed(2)),
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: muted, width: 1, type: "solid" },
          label: { color: muted, fontSize: 11, position: "insideStartTop" },
          data: [{ yAxis: 0, label: { formatter: "0" } }, { yAxis: -1, label: { formatter: "−1 (unit elastic)" } }],
        },
      }),
    ];
    opt.grid.right = 40;
    chart("c-elasticity").setOption(opt, true);
    tableView("c-elasticity", ["Week", "Rolling (12w)", "Arc (12w)"],
      w.week.map((d, i) => [d, isNum(w.elasticity_rolling[i]) ? w.elasticity_rolling[i].toFixed(2) : "–", isNum(w.elasticity_arc?.[i]) ? w.elasticity_arc[i].toFixed(2) : "–"]).reverse());
  }

  function renderGrowth() {
    const w = weekly();
    if (!w) return emptyChart("c-growth", "No token data");
    const [c1, c2] = SERIES();
    const opt = baseOption();
    opt.tooltip.formatter = tooltipFormatter((v) => signed(v));
    opt.yAxis.axisLabel.formatter = (v) => v + "%";
    opt.series = [
      { name: "Week-over-week", type: "bar", data: pairs(w.week, w.wow_pct), barMaxWidth: 12, itemStyle: { color: c1, borderRadius: 2 } },
      line("4-week growth (moving avg)", pairs(w.week, w.growth_4w_pct), c2, { endLabel: endLabel((v) => signed(v, 0)) }),
    ];
    opt.grid.right = 40;
    chart("c-growth").setOption(opt, true);
    tableView("c-growth", ["Week", "WoW %", "4-week %"], w.week.map((d, i) => [d, signed(w.wow_pct[i]), signed(w.growth_4w_pct[i])]).reverse());
  }

  function renderPrice() {
    const w = weekly();
    if (!w || !w.effective_price) return emptyChart("c-price", "No price data");
    const [c1, c2] = SERIES();
    const eff = reindex(w.effective_price), lfl = reindex(w.like_for_like_index);
    const opt = baseOption();
    opt.tooltip.formatter = tooltipFormatter((v) => v.toFixed(0));
    opt.series = [
      line("Average price (index)", pairs(w.week, eff), c1, { endLabel: endLabel((v) => v.toFixed(0)) }),
      line("Same-model price (index)", pairs(w.week, lfl), c2, { endLabel: endLabel((v) => v.toFixed(0)) }),
    ];
    opt.grid.right = 40;
    chart("c-price").setOption(opt, true);
    tableView("c-price", ["Week", "Avg $/1M", "Avg idx", "Same-model idx", "Price coverage"],
      w.week.map((d, i) => [d, usd(w.effective_price[i]), eff[i]?.toFixed(0) ?? "–", lfl[i]?.toFixed(0) ?? "–", pct((w.price_coverage[i] || 0) * 100, 0)]).reverse());
  }

  function renderMix() {
    const a = state.data?.tokens?.author_share;
    if (!a) return emptyChart("c-mix", "No author share data");
    const cut = cutoffDate();
    const idx = a.weeks.map((d, i) => (!cut || d >= cut ? i : -1)).filter((i) => i >= 0);
    const names = Object.keys(a.series);
    // Max 7 named makers + Other (fixed color order by latest share; never cycled past 8).
    const named = names.filter((n) => n !== "others").slice(0, 7);
    const other = idx.map((i) => names.filter((n) => !named.includes(n)).reduce((s, n) => s + (a.series[n][i] || 0), 0));
    const colors = SERIES();
    const surface = css("--surface");
    const opt = baseOption();
    opt.tooltip.formatter = tooltipFormatter((v) => pct(v));
    opt.yAxis = { ...opt.yAxis, max: 100, axisLabel: { ...opt.yAxis.axisLabel, formatter: "{value}%" } };
    const area = (name, data, color) => ({
      name, type: "line", stack: "share", data, showSymbol: false, smooth: false,
      lineStyle: { width: 1, color: surface }, areaStyle: { color, opacity: 0.85 }, itemStyle: { color }, emphasis: { focus: "series" },
    });
    opt.series = named.map((n, j) => area(n, idx.map((i) => [a.weeks[i], a.series[n][i]]), colors[j]));
    opt.series.push(area("Other", idx.map((i, k) => [a.weeks[i], other[k]]), css("--axis")));
    chart("c-mix").setOption(opt, true);
    tableView("c-mix", ["Week", ...named, "Other"], idx.map((i, k) => [a.weeks[i], ...named.map((n) => pct(a.series[n][i])), pct(other[k])]).reverse());
  }

  const SECTOR_ORDER = ["Information", "Finance & Insurance", "Professional Services", "Educational Services", "Health Care", "Manufacturing", "Retail Trade", "Construction"];

  function renderAdoption() {
    const ad = state.data?.adoption || {};
    const colors = SERIES();
    const ink = css("--ink");
    const opt = baseOption();
    opt.tooltip = { ...opt.tooltip, trigger: "axis", formatter: tooltipFormatter((v) => pct(v)) };
    opt.yAxis.axisLabel.formatter = "{value}%";
    const series = [];
    if (ad.global) series.push(line("World: people using AI", pts(ad.global), ink, { showSymbol: true, symbolSize: 8, endLabel: endLabel((v) => pct(v)), lineStyle: { width: 2.5 } }));
    const us = ad.us_business || {};
    if (us["All US businesses"]) series.push(line("All US businesses", pts(us["All US businesses"]), css("--ink-2"), { lineStyle: { type: [2, 3] }, endLabel: endLabel((v) => pct(v)) }));
    SECTOR_ORDER.filter((s) => us[s]).forEach((s, j) => series.push(line(s, pts(us[s]), colors[j], { lineStyle: { type: [6, 4] } })));
    if (!series.length) return emptyChart("c-adoption", "No adoption data");
    opt.series = series;
    opt.legend.top = 0;
    opt.grid.top = 60;
    opt.grid.right = 48;
    chart("c-adoption").setOption(opt, true);
    const rows = [];
    series.forEach((s) => s.data.forEach(([d, v]) => rows.push([d, s.name, pct(v)])));
    rows.sort((a, b) => (a[0] < b[0] ? 1 : -1));
    tableView("c-adoption", ["Date", "Series", "Value"], rows);
  }

  function renderSpeed() {
    const ad = state.data?.adoption || {};
    const use = ad.us_business?.["All US businesses"], exp = ad.us_business_expect?.["All US businesses"];
    if (!use) return emptyChart("c-speed", "No Census data");
    const [c1, c2] = SERIES();
    const opt = baseOption();
    opt.tooltip.formatter = tooltipFormatter((v) => pct(v));
    opt.yAxis.axisLabel.formatter = "{value}%";
    const series = [
      line("Using AI now", pts(use), c1, { endLabel: endLabel((v) => pct(v)) }),
    ];
    if (exp) series.push(line("Expect to use in 6 months", pts(exp), c2, { endLabel: endLabel((v) => pct(v)) }));
    const fit = ad.us_business_fit;
    if (fit?.curve) series.push(line("S-curve fit (projection)", fit.curve.map((p) => [p.date, p.value]), css("--muted"), { lineStyle: { type: [1, 4], width: 2 } }));
    opt.series = series;
    opt.grid.right = 48;
    chart("c-speed").setOption(opt, true);
    const note = document.querySelector("#c-speed").closest(".card").querySelector(".note");
    if (fit) {
      // A saturation pinned at the 100% bound means the series is still in its early, near-linear phase.
      const ceiling = fit.saturation >= 99 ? "no ceiling visible yet (still early in the S-curve)" : `levelling off near ${fit.saturation.toFixed(0)}%`;
      note.textContent = `Current use vs expected use in 6 months. S-curve fit (dotted): about ${fit.pp_per_quarter.toFixed(1)} pp per quarter now, ${ceiling}. Short series, so treat the projection as illustrative.`;
    }
    tableView("c-speed", ["Period ending", "Using AI %", "Expect in 6m %"], use.map((p, i) => [p.date, pct(p.value), pct(exp?.[i]?.value)]).reverse());
  }

  function renderCountries() {
    const ad = state.data?.adoption || {};
    const c = ad.countries || {};
    const names = Object.keys(c).sort((a, b) => (c[b].at(-1)?.value ?? 0) - (c[a].at(-1)?.value ?? 0));
    if (!names.length) return emptyChart("c-countries", "No country data");
    const colors = SERIES();
    const opt = baseOption();
    opt.tooltip.formatter = tooltipFormatter((v) => pct(v));
    opt.yAxis.axisLabel.formatter = "{value}%";
    opt.series = names.slice(0, 8).map((n, j) => line(n, pts(c[n]), colors[j], { showSymbol: true, symbolSize: 8 }));
    if (ad.global) opt.series.push(line("World", pts(ad.global), css("--ink"), { showSymbol: true, lineStyle: { width: 2.5 } }));
    opt.grid.top = 60;
    chart("c-countries").setOption(opt, true);
    const dates = [...new Set(names.flatMap((n) => c[n].map((p) => p.date)))].sort();
    tableView("c-countries", ["Country", ...dates], names.map((n) => [n, ...dates.map((d) => pct(c[n].find((p) => p.date === d)?.value))]));
  }

  function intensityRows(source) {
    return (state.data?.adoption?.intensity || []).filter((r) => r.source === source);
  }

  function renderGallup() {
    const rows = intensityRows("Gallup");
    if (!rows.length) return emptyChart("c-gallup", "No Gallup data");
    const [c1, c2, c3] = SERIES();
    const by = (m) => rows.filter((r) => r.metric === m).map((r) => [r.date, r.value]).sort();
    const opt = baseOption();
    opt.tooltip.formatter = tooltipFormatter((v) => pct(v, 0));
    opt.yAxis.axisLabel.formatter = "{value}%";
    const lab = endLabel((v) => pct(v, 0));
    opt.series = [
      line("Few times a year or more", by("total_few_times_year_plus"), c1, { showSymbol: true, endLabel: lab }),
      line("Few times a week or more", by("frequent_few_times_week_plus"), c2, { showSymbol: true, endLabel: lab }),
      line("Daily", by("daily"), c3, { showSymbol: true, endLabel: lab }),
    ];
    opt.grid.right = 40;
    chart("c-gallup").setOption(opt, true);
    tableView("c-gallup", ["Survey", "Metric", "% of employees"], rows.map((r) => [r.date, r.metric.replaceAll("_", " "), pct(r.value, 0)]).reverse());
  }

  function renderPew() {
    const rows = intensityRows("Pew");
    if (!rows.length) return emptyChart("c-pew", "No Pew data");
    const [c1, c2] = SERIES();
    const by = (m) => rows.filter((r) => r.metric === m).map((r) => [r.date, r.value]).sort();
    const opt = baseOption();
    opt.tooltip.formatter = tooltipFormatter((v) => pct(v, 0));
    opt.yAxis.axisLabel.formatter = "{value}%";
    const lab = endLabel((v) => pct(v, 0));
    opt.series = [
      line("Use chatbots", by("ever_used_chatbot"), c1, { showSymbol: true, endLabel: lab }),
      line("Use chatbots daily", by("daily"), c2, { showSymbol: true, symbolSize: 10, endLabel: lab }),
    ];
    opt.grid.right = 40;
    chart("c-pew").setOption(opt, true);
    const tpu = state.data?.adoption?.tokens_per_user;
    if (tpu) {
      $("#tpu-note").textContent = `% of US adults using chatbots, and daily users. Rough intensity proxy: OpenRouter's ${compact(tpu.weekly_tokens)} weekly tokens ÷ ${compact(tpu.ai_users)} AI users worldwide ≈ ${compact(tpu.tokens_per_user_week, 0)} tokens per user per week (OpenRouter only).`;
    }
    tableView("c-pew", ["Survey", "Metric", "% of adults"], rows.map((r) => [r.date, r.metric.replaceAll("_", " "), pct(r.value, 0)]).reverse());
  }

  // ---------- warnings mapped to cards ----------
  function renderWarnings() {
    const d = state.data;
    const banner = $("#banner");
    banner.replaceChildren();
    if (d.warnings?.length) {
      const det = document.createElement("details");
      det.className = "banner";
      const s = document.createElement("summary");
      s.textContent = `⚠ ${d.warnings.length} data note${d.warnings.length > 1 ? "s" : ""} from the last refresh`;
      const ul = document.createElement("ul");
      d.warnings.forEach((w) => { const li = document.createElement("li"); li.textContent = w; ul.appendChild(li); });
      det.append(s, ul);
      banner.appendChild(det);
    }
    document.querySelectorAll(".card[data-sources]").forEach((card) => {
      card.querySelector(".cardwarn")?.remove();
      const failed = card.dataset.sources.split(" ").filter((s) => d.errors?.[s]);
      if (failed.length) {
        const p = document.createElement("p");
        p.className = "cardwarn";
        p.textContent = `⚠ Source unavailable on last refresh: ${failed.map((s) => `${s} (${d.errors[s]})`).join("; ")}`;
        card.querySelector(".note").after(p);
      }
    });
  }

  function renderAll() {
    if (!state.data) return;
    $("#updated").textContent = "Updated " + new Date(state.data.generated_at).toLocaleString();
    renderWarnings();
    renderKpis();
    const renders = [renderIndex, renderElasticity, renderGrowth, renderPrice, renderMix, renderAdoption, renderSpeed, renderCountries, renderGallup, renderPew];
    for (const r of renders) {
      try { r(); } catch (e) { console.error(r.name, e); }
    }
  }

  // ---------- data loading & refresh ----------
  async function load() {
    const res = await fetch("data/dashboard.json?t=" + Date.now(), { cache: "no-store" });
    if (!res.ok) throw new Error("dashboard.json not found — run the pipeline first");
    state.data = await res.json();
    renderAll();
  }

  async function refresh() {
    const btn = $("#refresh");
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    document.querySelectorAll(".card").forEach((c) => c.classList.add("loading"));
    try {
      const r = await fetch("api/refresh", { method: "POST" });
      if (!r.ok) throw new Error("Refresh needs the local server (python serve.py)");
      let status;
      do {
        await new Promise((res) => setTimeout(res, 2000));
        status = await (await fetch("api/status", { cache: "no-store" })).json();
      } while (status.running);
      if (status.last_exit !== 0) {
        $("#updated").textContent = "Refresh finished with errors — showing last good data";
        console.warn(status.log_tail);
      }
      await load();
    } catch (e) {
      $("#updated").textContent = e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Refresh data";
      document.querySelectorAll(".card").forEach((c) => c.classList.remove("loading"));
    }
  }

  document.querySelectorAll("[data-range]").forEach((b) =>
    b.addEventListener("click", () => {
      state.range = Number(b.dataset.range);
      document.querySelectorAll("[data-range]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      renderAll();
    })
  );
  // api/refresh only exists under serve.py; the hosted copy is rebuilt by GitHub Actions.
  if (["localhost", "127.0.0.1"].includes(location.hostname)) {
    $("#refresh").addEventListener("click", refresh);
  } else {
    const btn = $("#refresh");
    btn.disabled = true;
    btn.textContent = "Updates daily at 7am CT";
    btn.title = "Rebuilt every morning by GitHub Actions";
  }
  window.addEventListener("resize", () => Object.values(state.charts).forEach((c) => c.resize()));
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderAll);
  new MutationObserver(renderAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  load().catch((e) => { $("#updated").textContent = e.message; });
})();
