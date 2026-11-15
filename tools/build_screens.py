"""Build the app's screen templates from the approved design (S90).

The design (the Claude Design canvas "Portfolio Lab redesign", exported to `design_s89/`, one `.dc.html` per screen) is the source of truth
for layout, words and behaviour. This script copies each design's markup into `src/pflab/app/static/s89/tpl/<screen>.html`:
the design's own data script is dropped (its numbers are samples), the shared header is dropped (the app draws one header for every screen),
links between design files become app routes, and every literal sample figure in the markup is replaced by a hole the screen fills from
the backend. A `<sc-for>` inside a `<select>` (which the HTML parser would drop) becomes a `data-for` attribute on its option.

Run from the repo folder after the design changes:  .venv\\Scripts\\python tools\\build_screens.py [design folder]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "pflab" / "app" / "static" / "s89" / "tpl"
SCREENS = {"Main": "home", "Money": "money", "Manage": "manage", "Calibration": "book", "Lab": "lab", "Graph": "graph", "Chat": "chat",
           "Agents": "agents", "Usage": "usage", "Settings": "settings", "Stock": "stock"}   # (the phone stacks these same screens: s89.css)
ROUTES = {f"{k}.dc.html": f"#/{v}" for k, v in SCREENS.items()}

# literal sample text in the markup -> holes (exact strings, checked: a missing one stops the build)
REPLACE = {
    "Main": [("height: 6px; width: 94%;", "height: 6px; width: {{story.w}};"),
        ("₹9,79,697", "{{money.v}}"), ("₹10,42,380", "{{book.v}}"),
        ("<span>You <b>+11.2%</b> · Claude <b>+11.0%</b> · baseline <b>+9.8%</b></span>", "<span>{{race}}</span>"),
        ("<span>Aug</span><span>Sep</span><span>Oct</span><span>Nov</span>", '<sc-for list="{{months}}" as="mo"><span>{{mo}}</span></sc-for>'),
        (">78</b> checks", ">{{counts.a}}</b> {{counts.al}}"), (">412</b> forecasts", ">{{counts.b}}</b> {{counts.bl}}"), (">12</b> filings", ">{{counts.c}}</b> {{counts.cl}}"),
        (">12%</span>", ">{{fall.v}}</span>"), ("chance of a 10% fall in the next 30 sessions", "{{fall.t}}"),
        ('aria-label="12 percent chance of a 10 percent fall in the next 30 sessions: calm"', 'aria-label="{{fall.aria}}"'),
        ('x2="77.7" y2="51.8"', 'x2="{{fall.nx}}" y2="{{fall.ny}}"'),
        ('<button type="button" onClick="{{n.undo}}" style="min-height: 32px; padding: 4px 12px; border-radius: 999px; border: 1px solid #C9C6BD; background: #FFFFFF; font: 500 12.5px Inter, sans-serif; cursor: pointer">Undo</button>', ''),
        (">94%</span>", ">{{story.p}}</span>"), ("Foreign money rotating into India", "{{story.t}}"), ("2 calls due 13 Nov · 3 more storylines in the graph", "{{story.s}}"),
    ],
    "Calibration": [("next look: Sun 22 Nov", "{{nextLook}}"),
                    ("<span>Jun</span><span>Jul</span><span>Aug</span><span>Sep</span><span>Oct</span><span>Nov</span>", '<sc-for list="{{months}}" as="mo"><span>{{mo}}</span></sc-for>')],
    "Lab": [("Your money, 200 possible futures", "{{sim.title}}"),
            ("Engle–Granger test on 250 daily closes, hedge ratio by least squares, half-life from the gap's pull back to zero.", "{{pair.method}}"),
            ("<span>Nov 2025</span><span>Mar</span><span>Jul</span><span>Nov 2026</span>", '<sc-for list="{{pair.months}}" as="mo"><span>{{mo}}</span></sc-for>'),
            ("<span>80 sessions ago</span><span>today</span><span>+20 sessions</span>", "<span>{{fc.from}}</span><span>today</span><span>{{fc.to}}</span>")],
    "Graph": [('value="HDFC Bank"', 'value="{{g.q}}" onKeydown="{{g.key}}" placeholder="a symbol, then Enter"'), (">HDFC Bank's year<", ">{{g.name}}'s year<"),
              ("Events for HDFC Bank over the last 12 months", "Events for {{g.name}} over the last 12 months"), (">HDFC Bank</div>", ">{{g.name}}</div>"),
              (">Banks</span>", ">{{g.t1}}</span>"), (">Nifty 50</span>", ">{{g.t2}}</span>"), (">your holding</span>", ">{{g.t3}}</span>"),
              (">ICICI Bank</div>", ">{{g.p1}}</div>"), (">Kotak Bank</div>", ">{{g.p2}}</div>"), (">Axis Bank</div>", ">{{g.p3}}</div>"),
              (">storyline · 94%<", ">{{g.s1p}}<"), (">Rotation into India<", ">{{g.s1}}<"), (">storyline · 55%<", ">{{g.s2p}}<"), (">Rate cut before March<", ">{{g.s2}}<"),
              (">18 Oct · results<", ">{{g.e1d}}<"), (">Q2 results beat<", ">{{g.e1t}}<"), (">24 Oct · deal<", ">{{g.e2d}}<"), (">Large block deal<", ">{{g.e2t}}<"),
              (">29 Oct · rating<", ">{{g.e3d}}<"), (">Rating upgraded<", ">{{g.e3t}}<"), (">Sep quarter · holdings<", ">{{g.e4d}}<"), (">Foreign stake up 1.2 pts<", ">{{g.e4t}}<"),
              (">18 Oct 2026, 17:42<", ">{{g.selAt}}<"), (">BSE filing<", ">{{g.selSrc}}<"), (">exchange code on that date<", ">{{g.selRule}}<"),
              (">thesis check · intact<", ">{{g.u1}}<"), (">rotation storyline +1<", ">{{g.u2}}<"), (">results-drift forecaster<", ">{{g.u3}}<"),
              (">99.9%<", ">{{g.st1}}<"), (">57k<", ">{{g.st3}}<"), (">filings linked<", ">events linked<"), (">articles<", ">names in the graph<"),
              ("and the storyline calls coming due: 13 Nov (India beats Asia, banks beat the index over 5 sessions) · 7 Dec (foreign buying stays positive, India beats Asia over 20 sessions)", "{{g.due}}"),
              (">Nov 2025<", ">{{g.y0}}<"), (">May 2026<", ">{{g.y1}}<"), (">Nov 2026<", ">{{g.y2}}<")],
    "Stock": [("HDFC Bank · you hold 120 · 6.1% of Claude's book", "{{s.title}}"), ("₹1,742.30", "{{s.price}}"), ("+1.4% today", "{{s.day}}"),
              ("Daily candles for HDFC Bank over 60 sessions", "Candles for {{s.name}} over {{s.n}} sessions"), ("stop ₹1,376 · 21% below", "{{s.stopText}}"),
              (">21% below<", ">{{s.stopPct}}<"), (">none · held long<", ">{{s.target}}<"), (">long-term<", ">{{s.tax}}<"), (">intact<", ">{{s.thesis}}<"),
              ("₹1,640 – ₹1,860", "{{s.range}}"), ("left: 22%; width: 56%;", "left: {{s.bl}}; width: {{s.bw}};"), ("left: 48%; top: -3px;", "left: {{s.bm}}; top: -3px;"), (">8 in 10 chance<", ">{{s.rangeLabel}}<"), ('href="#/graph"', 'href="#/graph/{{s.sym}}"')],
    "Money": [
        (">90 days<", ">{{days}}<"), ("90 sessions ago", "{{sel.from}}"), ("Claude's view · {{sel.conf}} sure", "{{sel.viewLine}}"),
        ("On its record, when it says {{sel.conf}} it has been right {{sel.calib}} of the time.", "{{sel.calibText}}"),
        ('href="#/stock" style="padding: 9px 14px;', 'href="#/stock/{{sel.sym}}" style="padding: 9px 14px;'),
        (">This year<", ">Since Claude's book started<"), ("After tax and costs. The paper book only counts if it beats the baseline.", "The paper book only counts if it beats its index."),
    ],
    "Chat": [('<a href="#" style="display: flex; flex-direction: column; gap: 1px;', '<a href="#/chat" onClick="{{c.open}}" style="display: flex; flex-direction: column; gap: 1px;'),
             ('<button type="button" aria-label="Attach a file" style="', '<button type="button" aria-label="Attach a file" onClick="{{attach}}" title="Attach a file" style="cursor: pointer; '),
             ('<circle cx="4" cy="4" r="4" fill="#2FA36B"></circle></svg>signed in · thinking running', '<circle cx="4" cy="4" r="4" fill="{{op.dot}}"></circle></svg>{{op.text}}'),
             ('<input id="chat-in" type="text"', '<input id="chat-in" aria-label="Message" autocomplete="off" type="text"')],
    "Usage": [('aria-label="412 thousand tokens used of the 1.1 million daily budget"', 'aria-label="{{u.aria}}"'), ('stroke-dasharray="133.7 218.2"', 'stroke-dasharray="{{u.dash}}"'),
              ('fill="#17181C">38%</text>', 'fill="#17181C">{{u.pct}}</text>'), ('line-height: 1.1">412k</div>', 'line-height: 1.1">{{u.used}}</div>'),
              ('>of 1.1M daily budget · resets at midnight<', '>of {{u.budget}} daily budget · resets at midnight<'), ('>thinking running · signed in on your plan<', '>{{u.state}}<'),
              ('font-weight: 600">17</div><div style="font-size: 13px; color: #3E4149">quick · about 6k tokens each', 'font-weight: 600">{{u.nq}}</div><div style="font-size: 13px; color: #3E4149">quick · {{u.aq}}'),
              ('font-weight: 600">3</div><div style="font-size: 13px; color: #3E4149">full · about 28k tokens each', 'font-weight: 600">{{u.nf}}</div><div style="font-size: 13px; color: #3E4149">full · {{u.af}}'),
              ('<div style="width: 85%; background: #93A9F6"></div><div style="width: 15%; background: #17181C"></div>', '<div style="width: {{u.wq}}; background: #93A9F6"></div><div style="width: {{u.wf}}; background: #17181C"></div>'),
              ('>17 of 20 chat answers took the quick road<', '>{{u.roadLine}}<'),
              ('font-weight: 600">6</div><div style="font-size: 13px; color: #3E4149">desk sessions', 'font-weight: 600">{{u.b1}}</div><div style="font-size: 13px; color: #3E4149">desk sessions'),
              ('font-weight: 600">3</div><div style="font-size: 13px; color: #3E4149">cases opened', 'font-weight: 600">{{u.b2}}</div><div style="font-size: 13px; color: #3E4149">cases opened'),
              ('font-weight: 600">1</div><div style="font-size: 13px; color: #3E4149">fix waiting for your Yes', 'font-weight: 600">{{u.b3}}</div><div style="font-size: 13px; color: #3E4149">{{u.b3l}}'),
              ('font-weight: 600">12k</div><div style="font-size: 13px; color: #3E4149">per alarm check', 'font-weight: 600">{{u.b4}}</div><div style="font-size: 13px; color: #3E4149">fix runs'),
              ('<text x="4" y="190">16 Oct</text><text x="352" y="190" text-anchor="middle">31 Oct</text><text x="716" y="190" text-anchor="end">15 Nov</text>',
               '<text x="4" y="190">{{u.x0}}</text><text x="352" y="190" text-anchor="middle">{{u.x1}}</text><text x="716" y="190" text-anchor="end">{{u.x2}}</text>'),
              ('<span style="color: #5B5E66">Left today</span><b>688k</b>', '<span style="color: #5B5E66">Left today</span><b>{{u.left}}</b>'),
              ('>last 20 sessions · darker = more<', '>model runs per day, last 20 days · darker = more<')],
    "Agents": [('<circle cx="4" cy="4" r="4" fill="#2FA36B"></circle></svg>signed in · no API key', '<circle cx="4" cy="4" r="4" fill="{{op.dot}}"></circle></svg>{{op.text}}'),
               ('>{{o.v}}</option>', '>{{o.l}}</option>'),
               ("Opus and Fable use your weekly limit faster than Sonnet or Haiku; Fable draws from its own weekly allowance. A change here applies from the agent's next run.",
                "Opus uses your weekly limit faster than Sonnet or Haiku. A change here applies from the agent's next run; the alarm reader runs on the local model.")],
}


# markup patterns -> app behaviour (regular expressions; each must match at least once)
CHAT_ACTS = ('<div style="display: flex; flex-wrap: wrap; gap: 8px"><sc-for list="{{%s.acts}}" as="a"><button type="button" onClick="{{a.go}}" style="padding: 7px 13px; border-radius: 999px; '
             'border: 1px solid {{a.bd}}; background: {{a.bg}}; color: {{a.fg}}; font: 600 13px Inter, sans-serif; cursor: pointer">{{a.label}}</button></sc-for></div>')
BTN = "padding: 8px 14px; border-radius: 999px; border: 1px solid #C9C6BD; background: #FFFFFF; color: #17181C; font: 500 13px Inter, sans-serif; min-height: 36px; cursor: pointer; text-decoration: none"
ACCT_ROW = ('<sc-for list="{{acct}}" as="a"><div style="display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 10px 0; border-bottom: 1px solid #F3F2EE">'
            '<svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="4" fill="{{a.fill}}" stroke="{{a.ring}}" stroke-width="2"></circle></svg>'
            '<div style="flex: 1 1 200px"><div style="font-weight: 600">{{a.name}}</div><div style="font-size: 12.5px; color: #5B5E66">{{a.sub}}</div></div>'
            '<sc-if value="{{a.btn}}"><button type="button" onClick="{{a.go}}" style="' + BTN + '">{{a.btn}}</button></sc-if>'
            '<sc-if value="{{a.link}}"><a href="{{a.href}}" style="' + BTN + '">{{a.link}}</a></sc-if></div></sc-for>')
SET_ROW = ('<sc-for list="{{rows}}" as="r"><div style="display: flex; flex-wrap: wrap; align-items: center; gap: 10px 12px; padding: 10px 0; border-bottom: 1px solid #F3F2EE">'
           '<sc-if value="{{r.head}}"><span style="flex: 1 1 100%; font-size: 12px; font-weight: 700; letter-spacing: .04em; color: #5B5E66; padding-top: 6px">{{r.head}}</span></sc-if>'
           '<div style="flex: 1 1 220px"><div style="font-weight: 600">{{r.name}}</div><div style="font-size: 12.5px; color: #5B5E66">{{r.sub}}</div></div>'
           '<sc-if value="{{r.pills}}"><div role="radiogroup" aria-label="{{r.name}}" style="display: flex; flex-wrap: wrap; gap: 6px"><sc-for list="{{r.pills}}" as="p">'
           '<button type="button" role="radio" aria-checked="{{p.on}}" onClick="{{p.pick}}" style="padding: 6px 12px; border-radius: 999px; border: 1px solid {{p.bd}}; background: {{p.bg}}; color: {{p.fg}}; font: {{p.w}} 12.5px Inter, sans-serif; cursor: pointer">{{p.label}}</button></sc-for></div></sc-if>'
           '<sc-if value="{{r.sw}}"><button type="button" role="switch" aria-checked="{{r.on}}" aria-label="{{r.name}}" onClick="{{r.flip}}" style="flex: none; width: 46px; height: 28px; border-radius: 999px; border: 0; background: {{r.bg}}; position: relative; cursor: pointer">'
           '<span style="position: absolute; left: {{r.kx}}; top: 3px; width: 22px; height: 22px; border-radius: 999px; background: #FFFFFF"></span></button></sc-if>'
           '<sc-if value="{{r.input}}"><input aria-label="{{r.name}}" type="{{r.input}}" value="{{r.val}}" placeholder="{{r.ph}}" onChange="{{r.set}}" onKeydown="{{r.key}}" style="flex: 1 1 200px; min-width: 0; border: 1px solid #E6E4DD; border-radius: 999px; padding: 10px 14px; font: 400 13px Inter, sans-serif; background: #FBFAF7">'
           '<button type="button" onClick="{{r.save}}" style="padding: 8px 14px; border-radius: 999px; border: 0; background: #17181C; color: #FFFFFF; font: 600 13px Inter, sans-serif; min-height: 36px; cursor: pointer">Save</button></sc-if>'
           '<sc-if value="{{r.btn}}"><button type="button" onClick="{{r.go}}" style="' + BTN + '">{{r.btn}}</button></sc-if></div></sc-for>')
REGEX = {
    "Settings": [(r'(<span[^>]*>Account</span>)\s*<div style="display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid #F3F2EE"><svg.*?Claude plan sign-in</div>.*?</div></div>\s*(<div style="display: flex; flex-direction: column; gap: 8px; padding-top: 4px">)',
                  lambda m: m.group(1) + ACCT_ROW + m.group(2)),
                 (r'<b style="font-family: \'Space Grotesk\', Inter, sans-serif; font-size: 20px">412k</b> <span style="color: #5B5E66">of 1\.1M</span>', '<b style="font-family: \'Space Grotesk\', Inter, sans-serif; font-size: 20px">{{tok.used}}</b> <span style="color: #5B5E66">of {{tok.budget}}</span>'),
                 (r'<div style="height: 8px; width: 38%;', '<div style="height: 8px; width: {{tok.w}};'),
                 (r'(<span[^>]*>Settings</span>)\s*<div style="display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid #F3F2EE"><div style="flex: 1"><div style="font-weight: 600">Chat answers</div>.*?Save</button></div>',
                  lambda m: m.group(1) + SET_ROW),
                 (r'(<span style="font-weight: 600">Standing instructions</span>)\s*(<div style="display: flex; align-items: center; gap: 10px; background: #F6F5F1;[^"]*">)<div style="flex: 1"><div([^>]*)>Gold buys paused</div><div([^>]*)>until 20 Nov</div></div><button type="button"( style="[^"]*")>Undo</button></div>.*?Undo</button></div>',
                  '\\1<sc-for list="{{rules}}" as="r">\\2<div style="flex: 1"><div\\3>{{r.name}}</div><div\\4>{{r.sub}}</div></div><sc-if value="{{r.undo}}"><button type="button" onClick="{{r.undo}}"\\5>Undo</button></sc-if></div></sc-for>'),
                 (r'>day 3 of 7<', '>{{wk.day}}<'), (r'<div style="height: 8px; width: 43%;', '<div style="height: 8px; width: {{wk.w}};'),
                 (r'When all pass: 60 days of bug fixes only\.', '{{wk.note}}'),
                 (r'font-size: 22px; font-weight: 600">1</span>', 'font-size: 22px; font-weight: 600">{{pr.n}}</span>'),
                 (r'(<div style="display: flex; align-items: center; gap: 10px; background: #FDF0E6;[^"]*">)<div style="flex: 1"><div([^>]*)>News top-up timed out</div><div([^>]*)>[^<]*</div></div></div>',
                  '<sc-for list="{{pr.rows}}" as="p">\\1<div style="flex: 1"><div\\2>{{p.t}}</div><div\\3>{{p.s}}</div></div></div></sc-for>'),
                 (r'<button type="button"( style="[^"]*")>Copy the list</button>', '<button type="button" onClick="{{pr.copy}}"\\1>{{pr.copyLabel}}</button>')],
    "Chat": [(r'<sc-if value="\{\{m\.hasUndo\}\}"[^>]*>.*?</sc-if>', '<sc-if value="{{m.hasActs}}">' + CHAT_ACTS % "m" + '</sc-if>'),
             (r'<div style="background: #FFFFFF; border: 2px solid #2F5BEA;([^"]*)">\s*<span([^>]*)>A fix is ready[^<]*</span>\s*<span([^>]*)>[^<]*</span>\s*<span([^>]*)>[^<]*</span>.*?All that needs you is on Home</a>\s*</div>',
              '<sc-for list="{{cards}}" as="k"><div style="background: #FFFFFF; border: 2px solid #2F5BEA;\\1"><span\\2>{{k.head}}</span><span\\3>{{k.text}}</span>'
              '<sc-if value="{{k.sub}}"><span\\4>{{k.sub}}</span></sc-if>' + CHAT_ACTS % "k" + '<a href="#/home" style="font-size: 12px; font-weight: 500">All that needs you is on Home</a></div></sc-for>'),
             (r'(<span style="font-weight: 600">Your standing instructions</span>)\s*(<div style="display: flex; align-items: center; gap: 10px; background: #F6F5F1;[^"]*">)<div style="flex: 1"><div([^>]*)>Gold buys paused</div><div([^>]*)>until 20 Nov</div></div><button type="button"( style="[^"]*")>Undo</button></div>.*?Undo</button></div>',
              '\\1<sc-for list="{{rules}}" as="r">\\2<div style="flex: 1"><div\\3>{{r.name}}</div><div\\4>{{r.sub}}</div></div><sc-if value="{{r.undo}}"><button type="button" onClick="{{r.undo}}"\\5>Undo</button></sc-if></div></sc-for>')],
    "Lab": [(r'<a href="#/chat"( style="[^"]*")>Backtest trading this gap</a>', r'<button type="button" onClick="{{pair.backtest}}">Backtest trading this gap</button>'),
            (r'<a href="#/graph"( style="[^"]*")>Save to the graph</a>', r'<button type="button" onClick="{{pair.save}}">Ask Claude to note it</button>'),
            (r"· last 250 sessions<", r"· last {{pair.days}} sessions<")],
    "Stock": [(r'(<div role="group" aria-label="Candle size"[^>]*>).*?</div>', r'\1<sc-for list="{{tfs}}" as="t"><button type="button" onClick="{{t.pick}}" style="padding: 7px 14px; border-radius: 999px; border: 0; background: {{t.bg}}; color: {{t.fg}}; font: {{t.w}} 13px Inter, sans-serif; cursor: pointer">{{t.label}}</button></sc-for></div>'),
              (r'<button type="button" aria-pressed="(?:true|false)"( style="[^"]*")>(Volume profile|Forecast|Stop|Events|Its trades)</button>', r'<span\1>\2</span>'),
              (r'<g><circle cx="234\.5".*?</g>\s*<g><circle cx="533\.5".*?</g>\s*<g><circle cx="625\.5".*?</g>', r'<sc-for list="{{evs}}" as="e"><g><circle cx="{{e.x}}" cy="414" r="9" fill="#FFFFFF" stroke="#17181C" stroke-width="1.5"></circle><text x="{{e.x}}" y="418" text-anchor="middle" font-size="10" font-weight="700" fill="#17181C">{{e.k}}</text><text x="{{e.x}}" y="436" text-anchor="middle" font-size="11" fill="#5B5E66">{{e.t}}</text></g></sc-for>'),
              (r'<span( style="[^"]*")>above its value area</span>.*?<span[^>]*>moves 0\.9× the market</span>', r'<sc-for list="{{sees}}" as="x"><span\1>{{x}}</span></sc-for>')],
    "Graph": [(r'<a href="#"( style="[^"]*")>\{\{g.selSrc\}\}</a>', r'<a href="{{g.selUrl}}"\1>{{g.selSrc}}</a>'),
              (r'>0</div>(<div[^>]*>)look-ahead', r'>{{g.st2}}</div>\1not linked yet'), (r'>passed</div>(<div[^>]*>nightly audit)', r'>{{g.st4}}</div>\1'),
              (r'<button type="button" aria-pressed="(?:true|false)"( style="[^"]*")>(Events|Storylines|Peers|News|US links)</button>', r'<span\1>\2</span>'),
              (r'<g( [^>]*)?>(?:<circle cx="[\d.]+" cy="30"( [^>]*)?></circle>)+</g>', r'<g\1><sc-for list="{{g.l0}}" as="c"><circle cx="{{c.x}}" cy="30"\2></circle></sc-for></g>'),
              (r'<g( [^>]*)?>(?:<circle cx="[\d.]+" cy="64"( [^>]*)?></circle>)+</g>', r'<g\1><sc-for list="{{g.l1}}" as="c"><circle cx="{{c.x}}" cy="64"\2></circle></sc-for></g>'),
              (r'<g( [^>]*)?>(?:<circle cx="[\d.]+" cy="98"( [^>]*)?></circle>)+</g>', r'<g\1><sc-for list="{{g.l2}}" as="c"><circle cx="{{c.x}}" cy="98"\2></circle></sc-for></g>'),
              (r'<g( [^>]*)?>(?:<circle cx="[\d.]+" cy="132"( [^>]*)?></circle>)+</g>', r'<g\1><sc-for list="{{g.l3}}" as="c"><circle cx="{{c.x}}" cy="132"\2></circle></sc-for></g>')],
}


def strip(t: str) -> str:
    body = t.split("<x-dc>", 1)[1].split("</x-dc>", 1)[0]
    body = re.sub(r"<helmet>.*?</helmet>", "", body, flags=re.S)
    body = re.sub(r'<script type="text/x-dc".*?</script>', "", body, flags=re.S)
    body = re.sub(r"<header\b.*?</header>", "", body, count=1, flags=re.S)
    for k, v in ROUTES.items():
        body = body.replace(f'href="{k}"', f'href="{v}"')
    return body


def select_loops(body: str) -> str:
    def fix(m):
        inner = re.sub(r'<sc-for list="\{\{([\w.]+)\}\}" as="(\w+)"[^>]*>\s*<option', r'<option data-for="\1" data-as="\2"', m.group(0))
        return inner.replace("</sc-for>", "")
    return re.sub(r"<select\b.*?</select>", fix, body, flags=re.S)


def build(design: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, screen in SCREENS.items():
        f = design / f"{name}.dc.html"
        if not f.exists():
            print(f"missing {f.name}: skipped")
            continue
        body = strip(f.read_text(encoding="utf-8"))
        for a, b in REPLACE.get(name, []):
            if a not in body:
                raise SystemExit(f"{name}: the literal {a!r} is not in the design any more: update REPLACE")
            body = body.replace(a, b)
        for pat, rep in REGEX.get(name, []):
            body, n = re.subn(pat, rep, body, flags=re.S)
            if not n:
                raise SystemExit(f"{name}: the pattern {pat!r} matched nothing: update REGEX")
        body = select_loops(body)
        (OUT / f"{screen}.html").write_text(f"<!-- built from design_s89/{name}.dc.html by tools/build_screens.py: do not edit by hand -->\n" + body.strip() + "\n", encoding="utf-8")
        print(f"{screen}: {len(body):,} chars")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "design_s89")
