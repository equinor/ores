// ═══════════════════════════════════════════════════════════════
// QUIZ.JS — Exercise templates + quiz engine
// ═══════════════════════════════════════════════════════════════

const CASE_NAMES = {
    nom:'1. Nominativ', gen:'2. Genitiv', dat:'3. Dativ',
    acc:'4. Akuzativ', voc:'5. Vokativ', loc:'6. Lokál', ins:'7. Instrumentál'
};
const CASE_Q = {
    nom:'kdo? co?', gen:'koho? čeho?', dat:'komu? čemu?',
    acc:'koho? co?', voc:'(oslovení)', loc:'o kom? o čem?', ins:'kým? čím?'
};
const GENDER_NAMES = {ma:'Muž. živ.',mi:'Muž. neživ.',f:'Ženský',n:'Střední'};

// ─── Exercise Templates ────────────────────────────────────────
// f: filter — '*'=any, 'p'=person, 'a'=animal, 'l'=place, 'f'=food,
//             't'=thing, 'x'=abstract, 'b'=body, 'r'=nature, 'v'=vehicle
//             comma=OR e.g. 'p,a'   '!'=NOT e.g. '!p'
const T = [
// ── NOM sg ──
{s:"To je {w}.",c:'nom',n:'sg',f:'*'},
{s:"{w} je tady.",c:'nom',n:'sg',f:'*'},
{s:"{w} stojí na ulici.",c:'nom',n:'sg',f:'p'},
{s:"{w} pracuje v továrně.",c:'nom',n:'sg',f:'p'},
{s:"{w} sedí na lavičce.",c:'nom',n:'sg',f:'p,a'},
{s:"{w} leží na stole.",c:'nom',n:'sg',f:'t,f'},
{s:"{w} je zavřený.",c:'nom',n:'sg',f:'l'},
{s:"{w} je drahý.",c:'nom',n:'sg',f:'t,f'},
{s:"{w} je krásná.",c:'nom',n:'sg',f:'f'},
{s:"{w} svítí.",c:'nom',n:'sg',f:'r'},
// ── NOM pl ──
{s:"To jsou {w}.",c:'nom',n:'pl',f:'*'},
{s:"{w} jsou na stole.",c:'nom',n:'pl',f:'t,f'},
{s:"{w} čekají venku.",c:'nom',n:'pl',f:'p'},
{s:"{w} jsou otevřené.",c:'nom',n:'pl',f:'l'},
{s:"{w} rostou v zahradě.",c:'nom',n:'pl',f:'r'},

// ── GEN sg — prepositions ──
{s:"Jsem bez {w}.",c:'gen',n:'sg',f:'*'},
{s:"Jdu do {w}.",c:'gen',n:'sg',f:'l'},
{s:"Vrátil se z {w}.",c:'gen',n:'sg',f:'l'},
{s:"Přišel od {w}.",c:'gen',n:'sg',f:'p'},
{s:"Bydlím vedle {w}.",c:'gen',n:'sg',f:'l,p'},
{s:"Kolem {w} je plot.",c:'gen',n:'sg',f:'l,r'},
{s:"Během {w} se hodně změnilo.",c:'gen',n:'sg',f:'x'},
{s:"Stojím u {w}.",c:'gen',n:'sg',f:'l,t'},
{s:"Blízko {w} je park.",c:'gen',n:'sg',f:'l'},
{s:"Podél {w} jsou stromy.",c:'gen',n:'sg',f:'r,l'},
{s:"Místo {w} vezmu autobus.",c:'gen',n:'sg',f:'v'},
{s:"Uprostřed {w} stojí socha.",c:'gen',n:'sg',f:'l'},
{s:"Podle {w} je to správné.",c:'gen',n:'sg',f:'x'},
{s:"Včetně {w} to stojí hodně.",c:'gen',n:'sg',f:'f,t'},
{s:"Kromě {w} přišli všichni.",c:'gen',n:'sg',f:'p'},
{s:"Dostala dopis od {w}.",c:'gen',n:'sg',f:'p'},
{s:"To je dům {w}.",c:'gen',n:'sg',f:'p'},
{s:"Bojím se {w}.",c:'gen',n:'sg',f:'a,p'},
{s:"Kolik stojí kilo {w}?",c:'gen',n:'sg',f:'f'},
// ── GEN pl ──
{s:"Koupil pět {w}.",c:'gen',n:'pl',f:'t,f'},
{s:"Bez {w} to nepůjde.",c:'gen',n:'pl',f:'*'},
{s:"Salon je plný {w}.",c:'gen',n:'pl',f:'p'},
{s:"Nemám dost {w}.",c:'gen',n:'pl',f:'*'},
{s:"Bydlím nedaleko {w}.",c:'gen',n:'pl',f:'l,r'},

// ── DAT sg — prepositions & verbs ──
{s:"Dám to {w}.",c:'dat',n:'sg',f:'p'},
{s:"Řeknu to {w}.",c:'dat',n:'sg',f:'p'},
{s:"Pomáhám {w}.",c:'dat',n:'sg',f:'p'},
{s:"Věřím {w}.",c:'dat',n:'sg',f:'p'},
{s:"Rozumím {w}.",c:'dat',n:'sg',f:'*'},
{s:"Jdu k {w}.",c:'dat',n:'sg',f:'l,p,r'},
{s:"Blížíme se k {w}.",c:'dat',n:'sg',f:'l,r'},
{s:"Díky {w} to jde.",c:'dat',n:'sg',f:'p,x'},
{s:"Kvůli {w} nemůžu jít.",c:'dat',n:'sg',f:'x,p'},
{s:"Naproti {w} je banka.",c:'dat',n:'sg',f:'l'},
{s:"Navzdory {w} jsme šli dál.",c:'dat',n:'sg',f:'r,x'},
{s:"Patří to {w}.",c:'dat',n:'sg',f:'p'},
{s:"Koupím dárek {w}.",c:'dat',n:'sg',f:'p'},
{s:"Zavolám {w}.",c:'dat',n:'sg',f:'p'},
// ── DAT pl ──
{s:"Dáme to {w}.",c:'dat',n:'pl',f:'p'},
{s:"Rozumíme {w}.",c:'dat',n:'pl',f:'*'},
{s:"Pomáháme {w}.",c:'dat',n:'pl',f:'p'},
{s:"Vzhledem k {w} to nejde.",c:'dat',n:'pl',f:'x'},

// ── ACC sg — verbs & prepositions ──
{s:"Vidím {w}.",c:'acc',n:'sg',f:'*'},
{s:"Mám {w}.",c:'acc',n:'sg',f:'*'},
{s:"Hledám {w}.",c:'acc',n:'sg',f:'*'},
{s:"Kupuji {w}.",c:'acc',n:'sg',f:'t,f'},
{s:"Potřebuji {w}.",c:'acc',n:'sg',f:'*'},
{s:"Čtu {w}.",c:'acc',n:'sg',f:'t'},
{s:"Znám {w}.",c:'acc',n:'sg',f:'p,l'},
{s:"Sednu si na {w}.",c:'acc',n:'sg',f:'t'},
{s:"Přejdeme přes {w}.",c:'acc',n:'sg',f:'l,r'},
{s:"Čekám na {w}.",c:'acc',n:'sg',f:'p,v'},
{s:"Pro {w} mám dárek.",c:'acc',n:'sg',f:'p'},
{s:"Jdu na {w}.",c:'acc',n:'sg',f:'l'},
{s:"Položil to za {w}.",c:'acc',n:'sg',f:'t,l'},
{s:"Pověsil obraz nad {w}.",c:'acc',n:'sg',f:'t'},
{s:"Jdu skrz {w}.",c:'acc',n:'sg',f:'l,r'},
// ── ACC pl ──
{s:"Vidím {w}.",c:'acc',n:'pl',f:'*'},
{s:"Kupujeme {w}.",c:'acc',n:'pl',f:'t,f'},
{s:"Hledáme {w}.",c:'acc',n:'pl',f:'*'},
{s:"Čteme {w}.",c:'acc',n:'pl',f:'t'},
{s:"Postavte se mezi {w}.",c:'acc',n:'pl',f:'l,t'},

// ── VOC sg ──
{s:"Ahoj, {w}!",c:'voc',n:'sg',f:'p'},
{s:"{w}, pojď sem!",c:'voc',n:'sg',f:'p'},
{s:"{w}, pomoz mi!",c:'voc',n:'sg',f:'p'},
{s:"Milý {w}!",c:'voc',n:'sg',f:'p'},
{s:"{w}, kde jsi?",c:'voc',n:'sg',f:'p'},
{s:"{w}, počkej!",c:'voc',n:'sg',f:'p'},
{s:"Pane {w}!",c:'voc',n:'sg',f:'p'},
// ── VOC pl ──
{s:"Milí {w}!",c:'voc',n:'pl',f:'p'},
{s:"{w}, pojďte sem!",c:'voc',n:'pl',f:'p'},

// ── LOC sg — prepositions ──
{s:"Bydlím v {w}.",c:'loc',n:'sg',f:'l'},
{s:"Jsem v {w}.",c:'loc',n:'sg',f:'l'},
{s:"Pracuji v {w}.",c:'loc',n:'sg',f:'l'},
{s:"Sedím na {w}.",c:'loc',n:'sg',f:'t'},
{s:"Mluvíme o {w}.",c:'loc',n:'sg',f:'*'},
{s:"Přemýšlím o {w}.",c:'loc',n:'sg',f:'*'},
{s:"Po {w} jdeme domů.",c:'loc',n:'sg',f:'f,x'},
{s:"Na {w} leží kniha.",c:'loc',n:'sg',f:'t'},
{s:"V {w} je temno.",c:'loc',n:'sg',f:'l,r'},
{s:"Při {w} se nemluví.",c:'loc',n:'sg',f:'f,x'},
{s:"Chodím po {w}.",c:'loc',n:'sg',f:'l,r'},
{s:"Čtu o {w}.",c:'loc',n:'sg',f:'*'},
{s:"Na {w} svítí slunce.",c:'loc',n:'sg',f:'r,l'},
{s:"V {w} je hodně lidí.",c:'loc',n:'sg',f:'l'},
{s:"Mám bolest v {w}.",c:'loc',n:'sg',f:'b'},
// ── LOC pl ──
{s:"Mluvíme o {w}.",c:'loc',n:'pl',f:'*'},
{s:"Wandruju po {w}.",c:'loc',n:'pl',f:'r,l'},
{s:"Píšou o {w}.",c:'loc',n:'pl',f:'*'},
{s:"V {w} je klid.",c:'loc',n:'pl',f:'l'},

// ── INS sg — prepositions ──
{s:"Jdu s {w}.",c:'ins',n:'sg',f:'p,a'},
{s:"Mluvím s {w}.",c:'ins',n:'sg',f:'p'},
{s:"Jedu {w}.",c:'ins',n:'sg',f:'v'},
{s:"Krájím {w}.",c:'ins',n:'sg',f:'t'},
{s:"Před {w} je park.",c:'ins',n:'sg',f:'l'},
{s:"Za {w} je les.",c:'ins',n:'sg',f:'l,t'},
{s:"Pod {w} leží kočka.",c:'ins',n:'sg',f:'t'},
{s:"Nad {w} létají ptáci.",c:'ins',n:'sg',f:'r,l'},
{s:"Společně s {w} to řeší.",c:'ins',n:'sg',f:'p'},
{s:"V souladu se {w} jedná.",c:'ins',n:'sg',f:'x'},
{s:"Kývl {w}.",c:'ins',n:'sg',f:'b'},
{s:"Mával {w}.",c:'ins',n:'sg',f:'b'},
{s:"Chléb s {w}.",c:'ins',n:'sg',f:'f'},
// ── INS pl ──
{s:"Jdeme s {w}.",c:'ins',n:'pl',f:'p'},
{s:"Mezi {w} je cesta.",c:'ins',n:'pl',f:'l,r'},
{s:"Za {w} je hřiště.",c:'ins',n:'pl',f:'r,t'},
{s:"Bavíme se s {w}.",c:'ins',n:'pl',f:'p'},
{s:"Mezi {w} jsou stromy.",c:'ins',n:'pl',f:'l,t'}
];

// ─── Filter matching ───────────────────────────────────────────
function matchType(nounType, filter) {
    if (filter === '*') return true;
    if (filter.startsWith('!')) return nounType !== filter.slice(1);
    return filter.split(',').includes(nounType);
}

// ─── Exercise generator ────────────────────────────────────────
function generateExercises(caseF, numF, genderF) {
    const pool = [];
    const nounKeys = Object.keys(NOUNS);
    for (const tmpl of T) {
        // Apply case/number filters
        if (caseF !== 'all' && tmpl.c !== caseF) continue;
        if (numF !== 'all' && tmpl.n !== numF) continue;
        // Find compatible nouns
        for (const nk of nounKeys) {
            const noun = NOUNS[nk];
            if (genderF !== 'all' && noun.gender !== genderF) continue;
            if (!matchType(noun.type, tmpl.f)) continue;
            // Skip vocative for non-animate
            if (tmpl.c === 'voc' && noun.gender !== 'ma' && noun.gender !== 'f' && noun.type !== 'p') continue;
            pool.push({ tmpl, nounKey: nk });
        }
    }
    return pool;
}

// ─── Form lookup ───────────────────────────────────────────────
function getForm(nounKey, cas, num) {
    const n = NOUNS[nounKey];
    return n ? (n[cas + '_' + num] || n.nom_sg) : '?';
}

// ─── Generate options (distractors) ────────────────────────────
function genOptions(nounKey, cas, num) {
    const correct = getForm(nounKey, cas, num);
    const noun = NOUNS[nounKey];
    const cases = ['nom','gen','dat','acc','voc','loc','ins'];
    const forms = new Set();
    for (const c of cases) {
        for (const n of ['sg','pl']) {
            const f = noun[c+'_'+n];
            if (f && f !== correct) forms.add(f);
        }
    }
    let distractors = shuffle([...forms]).slice(0, 3);
    // Pad with same-gender nouns if needed
    if (distractors.length < 3) {
        const sameG = Object.keys(NOUNS).filter(k => NOUNS[k].gender === noun.gender && k !== nounKey);
        for (const k of shuffle(sameG)) {
            if (distractors.length >= 3) break;
            const f = getForm(k, cas, num);
            if (f !== correct && !distractors.includes(f)) distractors.push(f);
        }
    }
    return { correct, options: shuffle([correct, ...distractors.slice(0,3)]) };
}

// ─── Shuffle utility ───────────────────────────────────────────
function shuffle(arr) {
    const a = [...arr];
    for (let i = a.length-1; i > 0; i--) {
        const j = Math.floor(Math.random()*(i+1));
        [a[i],a[j]] = [a[j],a[i]];
    }
    return a;
}

// ═══════════════════════════════════════════════════════════════
// QUIZ ENGINE
// ═══════════════════════════════════════════════════════════════
let quizQueue = [], curEx = null, curIdx = 0, answered = false;
let stats = loadStats();

function loadStats() {
    try {
        const s = JSON.parse(localStorage.getItem('czDeclStats2'));
        if (s && s.total !== undefined) return s;
    } catch(e) {}
    return { total:0, correct:0, byCase:{}, byGender:{}, history:[] };
}
function saveStats() { localStorage.setItem('czDeclStats2', JSON.stringify(stats)); }

function startQuiz() {
    const fc = document.getElementById('fCase').value;
    const fn = document.getElementById('fNum').value;
    const fg = document.getElementById('fGender').value;
    const pool = generateExercises(fc, fn, fg);
    if (pool.length === 0) {
        document.getElementById('quizArea').innerHTML =
            '<div class="empty"><div class="ico">🔍</div><p>Žádná cvičení pro tyto filtry. Zkuste jiné nastavení.</p></div>';
        return;
    }
    quizQueue = shuffle(pool).slice(0, Math.min(15, pool.length));
    curIdx = 0;
    showExercise();
}

function showExercise() {
    if (curIdx >= quizQueue.length) { showComplete(); return; }
    answered = false;
    const ex = quizQueue[curIdx];
    curEx = ex;
    const noun = NOUNS[ex.nounKey];
    const tmpl = ex.tmpl;
    const { correct, options } = genOptions(ex.nounKey, tmpl.c, tmpl.n);
    curEx._correct = correct;
    curEx._options = options;

    const sentHTML = tmpl.s.replace('{w}', '<span class="blank">???</span>');
    const numLabel = tmpl.n === 'sg' ? 'sg.' : 'pl.';
    const pct = Math.round((curIdx / quizQueue.length) * 100);
    document.getElementById('pTxt').textContent = `Otázka ${curIdx+1} z ${quizQueue.length}`;
    document.getElementById('pFill').style.width = pct+'%';

    document.getElementById('quizArea').innerHTML = `
        <div class="qcard">
            <div class="label">Doplňte správný tvar</div>
            <div class="sentence">${sentHTML} <span class="num-hint">(${numLabel})</span></div>
            <div class="noun-info">
                Podstatné jméno: <strong>${noun.nom_sg}</strong>
                <span class="gbadge ${noun.gender}">${GENDER_NAMES[noun.gender]}</span>
                · vzor: ${noun.pattern}
            </div>
            <div class="opts" id="optsGrid">
                ${options.map((o,i) => `<button class="opt" data-v="${o}" onclick="selOpt(this)">${o}</button>`).join('')}
            </div>
            <div class="brow">
                <button class="btn btn-p" id="btnChk" onclick="checkAnswer()" disabled>Zkontrolovat</button>
            </div>
            <div id="fbArea"></div>
        </div>`;
}

function selOpt(btn) {
    if (answered) return;
    document.querySelectorAll('.opt').forEach(b => b.classList.remove('sel'));
    btn.classList.add('sel');
    document.getElementById('btnChk').disabled = false;
}

function checkAnswer() {
    if (answered) return;
    answered = true;
    const sel = document.querySelector('.opt.sel');
    if (!sel) return;
    const tmpl = curEx.tmpl;
    const noun = NOUNS[curEx.nounKey];
    const correct = curEx._correct;
    const val = sel.dataset.v;
    const ok = val === correct;

    // Stats
    stats.total++; if (ok) stats.correct++;
    if (!stats.byCase[tmpl.c]) stats.byCase[tmpl.c] = {total:0,correct:0};
    stats.byCase[tmpl.c].total++; if (ok) stats.byCase[tmpl.c].correct++;
    if (!stats.byGender[noun.gender]) stats.byGender[noun.gender] = {total:0,correct:0};
    stats.byGender[noun.gender].total++; if (ok) stats.byGender[noun.gender].correct++;
    stats.history.push({noun:curEx.nounKey,case:tmpl.c,num:tmpl.n,correct:ok,time:Date.now()});
    if (stats.history.length > 300) stats.history = stats.history.slice(-300);
    saveStats(); updateScore();

    // Style buttons
    document.querySelectorAll('.opt').forEach(b => {
        b.classList.add('dis');
        if (b.dataset.v === correct) b.classList.add('ok');
        if (b.dataset.v === val && !ok) b.classList.add('bad');
    });

    // Fill blank
    const blank = document.querySelector('.blank');
    if (blank) {
        blank.textContent = correct;
        blank.style.borderBottomColor = ok ? 'var(--green)' : 'var(--err)';
        blank.style.color = ok ? 'var(--green)' : 'var(--err)';
    }

    const numN = tmpl.n === 'sg' ? 'singulár' : 'plurál';
    document.getElementById('fbArea').innerHTML = `
        <div class="fb ${ok?'ok':'bad'}">
            <div class="t">${ok ? '✓ Správně!' : '✗ Špatně!'}</div>
            <div class="d">
                <b>Pád:</b> ${CASE_NAMES[tmpl.c]} — ${CASE_Q[tmpl.c]}<br>
                <b>Číslo:</b> ${numN}<br>
                <b>Správná odpověď:</b> ${correct}<br>
                <b>Vzor:</b> ${noun.nom_sg} → ${correct} (${noun.pattern})
            </div>
        </div>
        <div class="brow">
            <button class="btn btn-p" onclick="nextEx()">Další →</button>
        </div>`;
    document.getElementById('btnChk').style.display = 'none';
}

function nextEx() { curIdx++; showExercise(); }

function showComplete() {
    const h = stats.history.slice(-quizQueue.length);
    const sc = h.filter(x=>x.correct).length;
    const tot = quizQueue.length;
    const pct = tot>0 ? Math.round((sc/tot)*100) : 0;
    document.getElementById('pFill').style.width = '100%';
    document.getElementById('pTxt').textContent = 'Kvíz dokončen!';
    document.getElementById('quizArea').innerHTML = `
        <div class="qcard" style="text-align:center;">
            <div style="font-size:3rem;margin-bottom:10px;">${pct>=80?'🎉':pct>=50?'👍':'💪'}</div>
            <h2 style="margin-bottom:6px;">Kvíz dokončen!</h2>
            <p style="font-size:1.2rem;margin-bottom:14px;">
                <strong>${sc}</strong> z <strong>${tot}</strong> správně
                <span style="color:${pct>=70?'var(--green)':'var(--err)'};">(${pct}%)</span>
            </p>
            <div class="brow">
                <button class="btn btn-p" onclick="startQuiz()">Nový kvíz ▶</button>
                <button class="btn btn-s" onclick="switchTab('statistiky')">Statistiky</button>
            </div>
        </div>`;
}

function updateScore() {
    const pct = stats.total>0 ? Math.round((stats.correct/stats.total)*100) : 0;
    document.getElementById('hdrScore').innerHTML =
        `${stats.correct} / ${stats.total}<span class="pct">${stats.total>0 ? ' ('+pct+'%)' : ''}</span>`;
}

// ═══════════════════════════════════════════════════════════════
// REFERENCE TAB
// ═══════════════════════════════════════════════════════════════
function buildNounSelector() {
    const sel = document.getElementById('nounSel');
    let html = '';
    const sorted = Object.keys(NOUNS).sort((a,b) => {
        const ga = NOUNS[a].gender, gb = NOUNS[b].gender;
        const order = {ma:0,mi:1,f:2,n:3};
        return (order[ga]||0) - (order[gb]||0) || a.localeCompare(b,'cs');
    });
    for (const k of sorted) {
        const n = NOUNS[k];
        html += `<span class="ntag" data-n="${k}" onclick="showParadigm('${k}')">${n.nom_sg} <span class="gbadge ${n.gender}" style="font-size:.6rem;">${n.gender.toUpperCase()}</span></span>`;
    }
    sel.innerHTML = html;
}

function showParadigm(nk) {
    document.querySelectorAll('.ntag').forEach(t => t.classList.remove('on'));
    document.querySelector(`.ntag[data-n="${nk}"]`)?.classList.add('on');
    const n = NOUNS[nk];
    const cs = ['nom','gen','dat','acc','voc','loc','ins'];
    const labels = ['1. Nominativ','2. Genitiv','3. Dativ','4. Akuzativ','5. Vokativ','6. Lokál','7. Instrumentál'];
    const qs = ['kdo? co?','koho? čeho?','komu? čemu?','koho? co?','—','o kom? o čem?','kým? čím?'];
    let rows = '';
    for (let i=0; i<7; i++) {
        rows += `<tr><td>${labels[i]}<br><small style="color:var(--muted)">${qs[i]}</small></td><td>${n[cs[i]+'_sg']}</td><td>${n[cs[i]+'_pl']}</td></tr>`;
    }
    document.getElementById('paradigmBox').innerHTML = `
        <div style="background:#fff;border-radius:8px;box-shadow:var(--shadow);padding:18px;margin-top:10px;">
            <h3 style="margin-bottom:3px;">${n.nom_sg} <span class="gbadge ${n.gender}">${GENDER_NAMES[n.gender]}</span></h3>
            <p style="color:var(--muted);margin-bottom:10px;">Vzor: ${n.pattern}</p>
            <table class="ptbl">
                <tr><th>Pád</th><th>Singulár</th><th>Plurál</th></tr>
                ${rows}
            </table>
        </div>`;
}

// ═══════════════════════════════════════════════════════════════
// STATISTICS TAB
// ═══════════════════════════════════════════════════════════════
function renderStats() {
    const pct = stats.total>0 ? Math.round((stats.correct/stats.total)*100) : 0;
    const recent = stats.history.slice(-20);
    const rc = recent.filter(h=>h.correct).length;
    const rp = recent.length>0 ? Math.round((rc/recent.length)*100) : 0;
    document.getElementById('statGrid').innerHTML = `
        <div class="scard"><div class="n">${stats.total}</div><div class="l">Celkem otázek</div></div>
        <div class="scard"><div class="n" style="color:var(--green)">${stats.correct}</div><div class="l">Správných</div></div>
        <div class="scard"><div class="n">${pct}%</div><div class="l">Celková úspěšnost</div></div>
        <div class="scard"><div class="n">${rp}%</div><div class="l">Posledních 20</div></div>`;
    const cases = ['nom','gen','dat','acc','voc','loc','ins'];
    let rows = '<tr><th>Pád</th><th>Otázky</th><th>Správně</th><th>%</th><th class="bc">Úspěšnost</th></tr>';
    for (const c of cases) {
        const d = stats.byCase[c] || {total:0,correct:0};
        const p = d.total>0 ? Math.round((d.correct/d.total)*100) : 0;
        const cls = p>=70?'g':p>=40?'m':'b';
        rows += `<tr><td>${CASE_NAMES[c]}</td><td>${d.total}</td><td>${d.correct}</td><td>${d.total>0?p+'%':'—'}</td><td class="bc"><div class="mb"><div class="f ${cls}" style="width:${p}%"></div></div></td></tr>`;
    }
    document.getElementById('caseStats').innerHTML = rows;
}

function resetStats() {
    if (confirm('Opravdu resetovat statistiky?')) {
        stats = {total:0,correct:0,byCase:{},byGender:{},history:[]};
        saveStats(); updateScore(); renderStats();
    }
}

// ═══════════════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════════════
function switchTab(tab) {
    document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
    document.querySelector(`.nav button[data-tab="${tab}"]`)?.classList.add('active');
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-'+tab)?.classList.add('active');
    if (tab === 'statistiky') renderStats();
}
document.querySelectorAll('.nav button').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// Keyboard shortcuts (desktop)
document.addEventListener('keydown', e => {
    if (e.key >= '1' && e.key <= '4' && !answered) {
        const btns = document.querySelectorAll('.opt');
        const idx = parseInt(e.key)-1;
        if (btns[idx]) selOpt(btns[idx]);
    }
    if (e.key === 'Enter') {
        if (!answered) { const s = document.querySelector('.opt.sel'); if (s) checkAnswer(); }
        else { const nb = document.querySelector('#fbArea .btn-p'); if (nb) nb.click(); }
    }
});

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════
(function init() {
    updateScore();
    buildNounSelector();
    const nounCount = Object.keys(NOUNS).length;
    document.getElementById('quizArea').innerHTML = `
        <div class="icard">
            <h2>Vítejte!</h2>
            <p>Procvičujte české skloňování podstatných jmen. Aplikace zobrazí větu s vynechaným tvarem.
               Znáte podstatné jméno v základním tvaru (1. pád, sg.) a musíte vybrat správný tvar.</p>
            <p>Databáze obsahuje <strong>${nounCount} podstatných jmen</strong> a <strong>${T.length} vzorových vět</strong>,
               z nichž se generují tisíce cvičení.</p>
            <p>Čeština má <strong>7 pádů</strong>:</p>
            <ul class="clist">
                <li><span class="cn">1</span> <span class="nm">Nominativ</span> — podmět — <span class="q">kdo? co?</span></li>
                <li><span class="cn">2</span> <span class="nm">Genitiv</span> — bez, do, od, z — <span class="q">koho? čeho?</span></li>
                <li><span class="cn">3</span> <span class="nm">Dativ</span> — k, díky, kvůli — <span class="q">komu? čemu?</span></li>
                <li><span class="cn">4</span> <span class="nm">Akuzativ</span> — přímý předmět — <span class="q">koho? co?</span></li>
                <li><span class="cn">5</span> <span class="nm">Vokativ</span> — oslovení — <span class="q">—</span></li>
                <li><span class="cn">6</span> <span class="nm">Lokál</span> — v, na, o, po — <span class="q">o kom? o čem?</span></li>
                <li><span class="cn">7</span> <span class="nm">Instrumentál</span> — s, před, za — <span class="q">kým? čím?</span></li>
            </ul>
            <p style="margin-top:12px;">Použijte filtry výše pro zaměření na konkrétní pád, číslo nebo rod. U každé otázky se zobrazuje <span class="num-hint">(sg.)</span> nebo <span class="num-hint">(pl.)</span>.</p>
            <div class="brow" style="margin-top:16px;">
                <button class="btn btn-p" onclick="startQuiz()" style="font-size:1.05rem;padding:14px 36px;">Začít cvičení ▶</button>
            </div>
        </div>`;
})();
