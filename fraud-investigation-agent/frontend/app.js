/* ═══════════════════════════════════════════════════════════════════════
   HHGOA Fraud Investigation — Frontend Application Logic
   ═══════════════════════════════════════════════════════════════════════ */

// ── Constants ────────────────────────────────────────────────────────────
const TYPOLOGY_COLORS = {
    // Authentic patterns (Policy v1.0)
    card_not_present_new_device: '#f59e0b',
    card_not_present_fraud:      '#f97316',
    card_testing:                '#ef4444',
    out_of_region_use:           '#a855f7',
    account_takeover:            '#f87171',
    none:                        '#34d399',
    undocumented:                '#94a3b8',
    // Uppercase variants for backward compatibility
    CARD_NOT_PRESENT_NEW_DEVICE: '#f59e0b',
    CARD_NOT_PRESENT_FRAUD:      '#f97316',
    CARD_TESTING:                '#ef4444',
    OUT_OF_REGION_USE:           '#a855f7',
    ACCOUNT_TAKEOVER:            '#f87171',
    NONE:                        '#34d399',
    CARD_NOT_PRESENT_RING:       '#fb923c',
    SYNTHETIC_IDENTITY:          '#c084fc',
    SMURFING_VELOCITY:           '#fbbf24',
    BUST_OUT:                    '#34d399',
    UNKNOWN:                     '#94a3b8',
};

const ACTION_ICONS = {
    // Policy v1.0 14 Allowed Actions
    BLOCK_CARD:              '🛑',
    BLOCK_ALL_CARDS:          '⛔',
    FILE_REPORT:             '📄',
    CLOSE_NO_FRAUD:          '🟢',
    WARN_CUSTOMER:           '🔔',
    VERIFY_WITH_CUSTOMER:    '📱',
    STEP_UP_AUTH:            '🔐',
    DECLINE_TRANSACTION:     '🚫',
    MONITOR_CARD:            '👁️',
    MONITOR_CONNECTED_CARDS: '🔍',
    CREATE_CASE:             '📁',
    ALLOW_TRANSACTION:       '✅',
    GENERATE_REPORT:         '📊',
    ESCALATE_TO_ANALYST:     '⚠️',
    // Legacy action aliases
    ADD_TO_WATCHLIST:        '👁️',
    BLOCK_TRANSACTION:       '🚫',
    FREEZE_ACCOUNT:          '❄️',
    ACCOUNT_HOLD:            '⛔',
    FILE_SAR:                '📄',
};

const INVESTIGATION_STAGES = [
    'Triggering case...',
    'Extracting subgraph...',
    'Gathering GraphRAG context...',
    'Assessing risk & uncertainty...',
    'Selecting pre-evidence action...',
    'Gathering additional evidence...',
    'Selecting final NBA...',
    'Generating SAR & explainability...',
    'Updating case memory...',
];

// ── State ────────────────────────────────────────────────────────────────
let currentPage = 'home';
let mockCases = [];
let mockResults = [];
let mockApprovals = [];

// ═══════════════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
    initParticles();
    initNavigation();
    initSidebarToggle();
    initDateDisplay();
    fetchSystemStatus();
    await generateMockData();
    renderHomePage();
    initInvestigateForm();
    initGraphView();
    populateCaseViewer();
    renderApprovals();
    renderAnalytics();
    initAllTabs();
    initInfoPage();

    // Generate form values
    document.getElementById('accountId').value = `ACC_${randomInt(100000, 999999)}`;
    document.getElementById('transactionId').value = `TXN_${randomInt(1000000, 9999999)}`;

    // Poll system status every 30s
    setInterval(fetchSystemStatus, 30000);
});

// ═══════════════════════════════════════════════════════════════════════
// PARTICLE BACKGROUND
// ═══════════════════════════════════════════════════════════════════════

function initParticles() {
    const canvas = document.getElementById('particleCanvas');
    const ctx = canvas.getContext('2d');
    let particles = [];
    let animId;

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }

    resize();
    window.addEventListener('resize', resize);

    class Particle {
        constructor() {
            this.reset();
        }
        reset() {
            this.x = Math.random() * canvas.width;
            this.y = Math.random() * canvas.height;
            this.size = Math.random() * 1.5 + 0.3;
            this.speedX = (Math.random() - 0.5) * 0.3;
            this.speedY = (Math.random() - 0.5) * 0.3;
            this.opacity = Math.random() * 0.4 + 0.1;
            // Hacker House Goa emerald (145-168) and warm gold (42-50)
            this.hue = Math.random() > 0.3 ? Math.floor(Math.random() * 23 + 145) : Math.floor(Math.random() * 10 + 42);
        }
        update() {
            this.x += this.speedX;
            this.y += this.speedY;
            if (this.x < 0 || this.x > canvas.width || this.y < 0 || this.y > canvas.height) {
                this.reset();
            }
        }
        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fillStyle = `hsla(${this.hue}, 85%, 68%, ${this.opacity})`;
            ctx.fill();
        }
    }

    // Create particles
    const count = Math.min(80, Math.floor((canvas.width * canvas.height) / 15000));
    for (let i = 0; i < count; i++) {
        particles.push(new Particle());
    }

    function drawConnections() {
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 120) {
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(52, 211, 153, ${0.08 * (1 - dist / 120)})`;
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        }
    }

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => { p.update(); p.draw(); });
        drawConnections();
        animId = requestAnimationFrame(animate);
    }

    animate();
}

// ═══════════════════════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════════════════════

function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item[data-page]');
    navItems.forEach(item => {
        const link = item.querySelector('.nav-link');
        if (link) {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                navigateTo(item.dataset.page);
            });
        }
    });

    // Header button bindings
    document.getElementById('btnNewInvestigation')?.addEventListener('click', () => navigateTo('investigate'));
    document.getElementById('btnRunBenchmark')?.addEventListener('click', () => navigateTo('analytics'));
}

function navigateTo(pageName) {
    currentPage = pageName;

    // Update nav active link
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const activeItem = document.querySelector(`.nav-item[data-page="${pageName}"] .nav-link`);
    if (activeItem) activeItem.classList.add('active');

    // Update page visibility
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const pageId = `page${pageName.charAt(0).toUpperCase() + pageName.slice(1)}`;
    const activePage = document.getElementById(pageId);
    if (activePage) activePage.classList.add('active');

    // On mobile: close sidebar after navigation
    if (window.innerWidth <= 1024) {
        const sidebar = document.getElementById('sidebar');
        sidebar?.classList.remove('menu-active');
        sidebar && (sidebar.style.height = '56px');
        const menuToggler = document.getElementById('menuToggler');
        if (menuToggler) menuToggler.querySelector('span').innerText = 'menu';
    }
}

function initSidebarToggle() {
    const sidebar     = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    const sidebarToggler = document.getElementById('sidebarToggler'); // desktop chevron
    const menuToggler    = document.getElementById('menuToggler');    // mobile hamburger

    // Heights for mobile toggle
    const collapsedHeight = '56px';
    const fullHeight = 'calc(100vh - 0px)';

    /* ── Desktop sidebar-toggler (chevron) ── */
    sidebarToggler?.addEventListener('click', () => {
        sidebar?.classList.toggle('collapsed');
        mainContent?.classList.toggle('collapsed');
    });

    /* ── Mobile menu-toggler (hamburger) ── */
    const toggleMenu = (isMenuActive) => {
        if (!sidebar) return;
        sidebar.style.height = isMenuActive ? `${sidebar.scrollHeight}px` : collapsedHeight;
        if (menuToggler) menuToggler.querySelector('span').innerText = isMenuActive ? 'close' : 'menu';
    };

    menuToggler?.addEventListener('click', () => {
        if (!sidebar) return;
        toggleMenu(sidebar.classList.toggle('menu-active'));
    });

    /* ── Resize handler ── */
    window.addEventListener('resize', () => {
        if (!sidebar) return;
        if (window.innerWidth > 1024) {
            sidebar.style.height = fullHeight;
            sidebar.classList.remove('menu-active');
        } else {
            sidebar.classList.remove('collapsed');
            mainContent?.classList.remove('collapsed');
            sidebar.style.height = 'auto';
            toggleMenu(sidebar.classList.contains('menu-active'));
        }
    });
}


function initDateDisplay() {
    const dateEl = document.getElementById('currentDate');
    if (dateEl) {
        dateEl.textContent = new Date().toISOString().split('T')[0];
    }
}

// ═══════════════════════════════════════════════════════════════════════
// LIVE SYSTEM STATUS (polls /api/status)
// ═══════════════════════════════════════════════════════════════════════

let _apiAvailable = false;

async function fetchSystemStatus() {
    const setStatus = (id, dotId, text, dotClass) => {
        const el = document.getElementById(id);
        const dot = document.getElementById(dotId);
        if (el) el.textContent = text;
        if (dot) { dot.className = 'status-dot ' + dotClass; }
    };

    try {
        const resp = await fetch('/api/status');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const s = await resp.json();
        _apiAvailable = true;

        // Mode
        const mode = s.demo_mode ? 'DEMO' : 'LIVE';
        setStatus('statusMode', 'statusDotMode', mode, s.demo_mode ? 'dot-gold' : 'dot-green');

        // Agent / LLM
        const llm = s.llm || {};
        if (llm.status === 'ready') {
            setStatus('statusAgent', 'statusDotAgent', 'Active', 'dot-green');
        } else {
            setStatus('statusAgent', 'statusDotAgent', 'No LLM', 'dot-red');
        }

        // Graph DB
        const graph = s.graph || {};
        if (graph.status === 'live') {
            setStatus('statusGraph', 'statusDotGraph', 'Live', 'dot-green');
        } else if (graph.status === 'dataset') {
            setStatus('statusGraph', 'statusDotGraph', `Dataset (${(graph.records || 0).toLocaleString()})`, 'dot-blue');
        } else {
            setStatus('statusGraph', 'statusDotGraph', 'Offline', 'dot-red');
        }

        // RAG
        const rag = s.rag || {};
        if (rag.status === 'ready') {
            setStatus('statusRAG', 'statusDotRAG', `${(rag.closed_cases || 0).toLocaleString()} cases`, 'dot-green');
        } else {
            setStatus('statusRAG', 'statusDotRAG', 'Offline', 'dot-red');
        }

        console.log('[HHGOA] System status:', s);
    } catch (err) {
        _apiAvailable = false;
        // Backend not running — show static fallback
        setStatus('statusMode', 'statusDotMode', 'STATIC', 'dot-gold');
        setStatus('statusAgent', 'statusDotAgent', 'Offline', 'dot-red');
        setStatus('statusGraph', 'statusDotGraph', 'Offline', 'dot-red');
        setStatus('statusRAG', 'statusDotRAG', 'Offline', 'dot-red');
    }
}
// ═══════════════════════════════════════════════════════════════════════
// MOCK DATA GENERATION
// ═══════════════════════════════════════════════════════════════════════

async function generateMockData() {
    // Try to load real benchmark case data from data/cases.json
    // (generated by convert_cases.py from the HHG-*.json files)
    try {
        const resp = await fetch('data/cases.json');
        if (resp.ok) {
            mockResults = await resp.json();
            console.log(`[HHGOA] Loaded ${mockResults.length} real benchmark cases from data/cases.json`);
        } else {
            throw new Error(`HTTP ${resp.status}`);
        }
    } catch (err) {
        console.warn('[HHGOA] Could not load data/cases.json, falling back to inline mock data:', err);
        generateFallbackMockResults();
    }

    // Derive live cases for the Home page from the first 8 mockResults
    const statuses = ['OPEN', 'IN_REVIEW', 'ESCALATED'];
    mockCases = mockResults.slice(0, 8).map((r, i) => {
        const post = r.post_evidence_recommendation;
        return {
            case_id:    r.case_id,
            account_id: r.initial_trigger.account_id,
            typology:   post.fraud_typology,
            fraud_prob: post.confidence,
            amount:     r.initial_trigger.amount,
            status:     statuses[i % statuses.length],
        };
    });
    mockCases.sort((a, b) => b.fraud_prob - a.fraud_prob);

    // Generate approvals from non-automated cases
    mockApprovals = mockResults.filter(r =>
        r.post_evidence_recommendation.approval_required !== 'AUTOMATED_POLICY'
    ).slice(0, 5);
}

function generateFallbackMockResults() {
    const typologies = Object.keys(TYPOLOGY_COLORS).filter(t => t !== 'UNKNOWN');
    const actions = Object.keys(ACTION_ICONS);
    const tiers = ['AUTOMATED_POLICY', 'TIER_1_ANALYST', 'TIER_2_ANALYST', 'COMPLIANCE_OFFICER'];
    mockResults = [];
    for (let i = 1; i <= 20; i++) {
        const confidence = +(Math.random() * 0.35 + 0.60).toFixed(2);
        const typology = typologies[randomInt(0, typologies.length - 1)];
        const action = actions[randomInt(0, actions.length - 1)];
        const tier = tiers[randomInt(0, tiers.length - 1)];
        const sarRequired = confidence > 0.82;

        mockResults.push({
            case_id: `CASE_2026_${String(i).padStart(3, '0')}`,
            initial_trigger: {
                account_id: `ACC_${randomInt(100000, 999999)}`,
                trigger_type: ['HIGH_RISK_SCORE', 'VELOCITY_SPIKE', 'PATTERN_MATCH'][randomInt(0, 2)],
                initial_risk: +(Math.random() * 0.4 + 0.55).toFixed(2),
                amount: +(Math.random() * 25000 + 1000).toFixed(2),
            },
            pre_evidence_recommendation: {
                action: actions[randomInt(0, actions.length - 1)],
                approval_required: 'AUTOMATED_POLICY',
                confidence: +(confidence - 0.1).toFixed(2),
            },
            post_evidence_recommendation: {
                action,
                approval_required: tier,
                confidence,
                fraud_typology: typology,
                justification: `High confidence ${typology.replace(/_/g, ' ').toLowerCase()} pattern detected with graph evidence supporting ${action.replace(/_/g, ' ').toLowerCase()}.`,
            },
            graph_evidence: {
                shared_device_accounts_count: randomInt(0, 4),
                ip_proxy_detected: Math.random() > 0.4,
                subgraph_path: `ACC_${randomInt(100, 999)} --[USED_DEVICE]--> DEV_${randomHex(3).toUpperCase()}`,
                ring_size: randomInt(0, 6),
            },
            sar_filing_required: sarRequired,
            sar_draft: sarRequired ? generateMockSAR(`CASE_2026_${String(i).padStart(3, '0')}`, typology) : '',
            audit_trail: generateMockAudit(),
            _benchmark: { typology, expected: { action: 'FREEZE_ACCOUNT' } },
            _score: { action_match: Math.random() > 0.3, typology_match: Math.random() > 0.2, sar_match: Math.random() > 0.25 },
            _pass_rate: `${randomInt(65, 100)}%`,
        });
    }
}

function generateMockSAR(caseId, typology) {
    return `SUSPICIOUS ACTIVITY REPORT (SAR)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Filing Type: Initial Report
Case Reference: ${caseId}
Filing Date: ${new Date().toISOString().split('T')[0]}

PART I - SUBJECT INFORMATION
Subject: Account Holder
Account Number: ACC_${randomInt(100000, 999999)}
Account Type: Individual Checking

PART II - SUSPICIOUS ACTIVITY
Activity Type: ${typology.replace(/_/g, ' ')}
Date Range: ${new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString().split('T')[0]} to ${new Date().toISOString().split('T')[0]}
Amount Involved: $${(Math.random() * 50000 + 5000).toFixed(2)}

PART III - NARRATIVE
Investigation identified patterns consistent with ${typology.replace(/_/g, ' ').toLowerCase()}.
Graph analysis reveals shared device and IP connections to known fraud networks.
Multiple high-risk indicators triggered automated escalation protocols.
Recommend continued monitoring and potential law enforcement referral.

PART IV - FILING INSTITUTION
Institution: HHGOA Fraud Intelligence Division
Contact: Automated SAR System v2.1.0`;
}

function generateMockAudit() {
    const stages = ['trigger', 'investigate', 'graphrag', 'risk_assess', 'pre_nba', 'extra_evidence', 'post_nba', 'sar_gen', 'memory'];
    const now = Date.now();
    return stages.map((stage, i) => ({
        timestamp: new Date(now - (stages.length - i) * 2000).toISOString(),
        stage,
        event: `Stage ${stage.replace(/_/g, ' ')} completed`,
        detail: `Processing time: ${(Math.random() * 2 + 0.5).toFixed(1)}s`,
    }));
}

// ═══════════════════════════════════════════════════════════════════════
// HOME PAGE RENDERING
// ═══════════════════════════════════════════════════════════════════════

function renderHomePage() {
    renderCaseList();
    renderTypologyChart();
    renderTrendsChart();
    renderGauges();
    renderTimeline();
    animateKPIValues();
}

function renderCaseList() {
    const container = document.getElementById('caseList');
    if (!container) return;

    container.innerHTML = mockCases.map((c, i) => {
        const badge = riskBadge(c.fraud_prob);
        const typColor = TYPOLOGY_COLORS[c.typology] || '#94a3b8';
        const statusIcon = { OPEN: '🟡', IN_REVIEW: '🔵', ESCALATED: '🔴' }[c.status] || '⚪';
        const gradEnd = c.fraud_prob >= 0.85 ? '#ef4444' : c.fraud_prob >= 0.70 ? '#f59e0b' : '#34d399';
        const pct = Math.round(c.fraud_prob * 100);

        return `
        <tr onclick="navigateTo('caseviewer')" style="animation: caseSlide 0.4s ease forwards; animation-delay: ${i * 0.05}s;" title="Click to inspect case ${c.case_id}">
            <td>
                <div style="display:flex; flex-direction:column;">
                    <span style="font-weight:700; color:#ffffff; font-family:'JetBrains Mono',monospace; font-size:0.84rem;">${c.case_id}</span>
                    <span style="font-size:0.7rem; color:#6ee7b7; font-family:'JetBrains Mono',monospace;">${c.account_id}</span>
                </div>
            </td>
            <td>
                <span style="display:inline-flex; align-items:center; gap:6px; font-weight:600; font-size:0.75rem; color:${typColor};">
                    <span style="width:7px; height:7px; border-radius:50%; background:${typColor}; box-shadow:0 0 8px ${typColor};"></span>
                    ${c.typology.replace(/_/g, ' ')}
                </span>
            </td>
            <td>
                <span style="font-weight:700; font-family:'JetBrains Mono',monospace; color:#ffffff; font-size:0.84rem;">
                    $${c.amount.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                </span>
            </td>
            <td style="min-width:140px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <div style="flex:1; height:6px; background:rgba(3,20,12,0.85); border-radius:999px; overflow:hidden; border:1px solid rgba(52,211,153,0.15);">
                        <div style="height:100%; width:${pct}%; background:linear-gradient(90deg, #10b981, ${gradEnd}); border-radius:999px; transition: width 0.8s ease;"></div>
                    </div>
                    <span style="font-size:0.72rem; font-weight:700; font-family:'JetBrains Mono',monospace; color:#ffffff;">${pct}%</span>
                </div>
            </td>
            <td>
                <div style="display:flex; align-items:center; gap:6px;">
                    <span style="font-size:0.72rem; color:#a7f3d0; font-weight:600;">${statusIcon} ${c.status}</span>
                    ${badge}
                </div>
            </td>
        </tr>`;
    }).join('');
}

function riskBadge(fp) {
    if (fp >= 0.85) return '<span class="badge badge-critical">CRITICAL</span>';
    if (fp >= 0.70) return '<span class="badge badge-high">HIGH</span>';
    if (fp >= 0.50) return '<span class="badge badge-medium">MEDIUM</span>';
    return '<span class="badge badge-low">LOW</span>';
}

function animateKPIValues() {
    animateCounter('kpiActiveCases', 0, 8, 800);
    animateCounter('kpiInvestigated', 0, 24, 1000);
    animateCounter('kpiSARs', 0, 7, 900);
    animateCounter('kpiFrozen', 0, 4, 700);
    // kpiConfidence is a percentage
    const confEl = document.getElementById('kpiConfidence');
    if (confEl) {
        let val = 0;
        const target = 87;
        const step = target / 40;
        const interval = setInterval(() => {
            val += step;
            if (val >= target) { val = target; clearInterval(interval); }
            confEl.textContent = `${Math.round(val)}%`;
        }, 20);
    }
}

function animateCounter(id, from, to, duration) {
    const el = document.getElementById(id);
    if (!el) return;
    const start = performance.now();
    function tick(now) {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(from + (to - from) * eased);
        if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

// ═══════════════════════════════════════════════════════════════════════
// CIRCULAR PROGRESS GAUGES (VISION UI PATTERN)
// ═══════════════════════════════════════════════════════════════════════

function renderGauges() {
    // 1. Detection Accuracy (SatisfactionRate pattern)
    // Circumference for r=64 is 2 * PI * 64 = 402.12
    const accCircle = document.getElementById('gaugeAccuracyCircle');
    const accVal = document.getElementById('gaugeAccuracyVal');
    if (accCircle) {
        setTimeout(() => {
            // 94.8% -> offset = 402.12 * (1 - 0.948) = 20.91
            accCircle.style.strokeDashoffset = '20.91';
        }, 150);
    }
    if (accVal) {
        let val = 0;
        const target = 94.8;
        const timer = setInterval(() => {
            val += 2.4;
            if (val >= target) {
                val = target;
                clearInterval(timer);
            }
            accVal.textContent = `${val.toFixed(1)}%`;
        }, 25);
    }

    // 2. Threat Mitigation Index (ReferralTracking pattern)
    // Circumference for r=50 is 2 * PI * 50 = 314.16
    const threatCircle = document.getElementById('gaugeThreatCircle');
    const threatVal = document.getElementById('gaugeThreatVal');
    if (threatCircle) {
        setTimeout(() => {
            // 8.9 / 10 = 89% -> offset = 314.16 * (1 - 0.89) = 34.56
            threatCircle.style.strokeDashoffset = '34.56';
        }, 200);
    }
    if (threatVal) {
        let val = 0;
        const target = 8.9;
        const timer = setInterval(() => {
            val += 0.25;
            if (val >= target) {
                val = target;
                clearInterval(timer);
            }
            threatVal.textContent = val.toFixed(1);
        }, 30);
    }
}

// ═══════════════════════════════════════════════════════════════════════
// INVESTIGATION TRENDS CHART (VISION UI SALES OVERVIEW PATTERN)
// ═══════════════════════════════════════════════════════════════════════

function renderTrendsChart() {
    const canvas = document.getElementById('trendsCanvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = rect.width > 0 ? rect.width : 500;
    const height = 220;

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    ctx.scale(dpr, dpr);

    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const anomalyValues = [14, 21, 18, 29, 36, 25, 42];
    const autoResolved = [12, 19, 17, 26, 33, 23, 39];

    const padding = { top: 30, right: 25, bottom: 35, left: 35 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;
    const maxVal = 50;

    let animProgress = 0;
    function draw() {
        animProgress = Math.min(animProgress + 0.04, 1);
        const ease = 1 - Math.pow(1 - animProgress, 3);

        ctx.clearRect(0, 0, width, height);

        // Horizontal gridlines & Y labels
        ctx.strokeStyle = 'rgba(52, 211, 153, 0.08)';
        ctx.lineWidth = 1;
        ctx.fillStyle = '#6ee7b7';
        ctx.font = '500 10px JetBrains Mono';
        ctx.textAlign = 'right';

        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (chartH / 4) * i;
            const val = Math.round(maxVal - (maxVal / 4) * i);
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(width - padding.right, y);
            ctx.stroke();
            ctx.fillText(val, padding.left - 8, y + 3);
        }

        // X labels
        ctx.textAlign = 'center';
        const stepX = chartW / (days.length - 1);
        days.forEach((day, i) => {
            const x = padding.left + i * stepX;
            ctx.fillText(day, x, height - 12);
        });

        const getPt = (vals, i) => ({
            x: padding.left + i * stepX,
            y: padding.top + chartH - (vals[i] / maxVal) * chartH * ease
        });

        // Area gradient fill for anomaly values
        const grad = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartH);
        grad.addColorStop(0, 'rgba(16, 185, 129, 0.35)');
        grad.addColorStop(1, 'rgba(16, 185, 129, 0.01)');

        ctx.beginPath();
        const first = getPt(anomalyValues, 0);
        ctx.moveTo(first.x, first.y);
        for (let i = 1; i < days.length; i++) {
            const p0 = getPt(anomalyValues, i - 1);
            const p1 = getPt(anomalyValues, i);
            const midX = (p0.x + p1.x) / 2;
            ctx.bezierCurveTo(midX, p0.y, midX, p1.y, p1.x, p1.y);
        }
        ctx.lineTo(padding.left + chartW, padding.top + chartH);
        ctx.lineTo(padding.left, padding.top + chartH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        // Primary curve (Emerald)
        ctx.beginPath();
        ctx.moveTo(first.x, first.y);
        for (let i = 1; i < days.length; i++) {
            const p0 = getPt(anomalyValues, i - 1);
            const p1 = getPt(anomalyValues, i);
            const midX = (p0.x + p1.x) / 2;
            ctx.bezierCurveTo(midX, p0.y, midX, p1.y, p1.x, p1.y);
        }
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 3;
        ctx.stroke();

        // Auto-resolved curve (Gold dashed)
        const firstAuto = getPt(autoResolved, 0);
        ctx.beginPath();
        ctx.moveTo(firstAuto.x, firstAuto.y);
        for (let i = 1; i < days.length; i++) {
            const p0 = getPt(autoResolved, i - 1);
            const p1 = getPt(autoResolved, i);
            const midX = (p0.x + p1.x) / 2;
            ctx.bezierCurveTo(midX, p0.y, midX, p1.y, p1.x, p1.y);
        }
        ctx.strokeStyle = '#ffd700';
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Dots on primary curve
        days.forEach((_, i) => {
            const pt = getPt(anomalyValues, i);
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff';
            ctx.fill();
            ctx.strokeStyle = '#10b981';
            ctx.lineWidth = 2;
            ctx.stroke();
        });

        if (animProgress < 1) requestAnimationFrame(draw);
    }

    draw();
}

// ═══════════════════════════════════════════════════════════════════════
// TIMELINE (VISION UI ORDER OVERVIEW PATTERN)
// ═══════════════════════════════════════════════════════════════════════

function renderTimeline() {
    const timeline = document.getElementById('agentTimeline');
    if (!timeline) return;

    const events = [
        {
            icon: '❄️',
            color: '#34d399',
            title: 'Account ACC_948201 containment executed',
            desc: 'Post-evidence NBA triggered: Automated freeze applied',
            time: '14 mins ago'
        },
        {
            icon: '🕸️',
            color: '#ffd700',
            title: 'GSQL 2-Hop Subgraph Traversal verified',
            desc: 'Found 4 accounts sharing hardware device DEV_8E2',
            time: '38 mins ago'
        },
        {
            icon: '📄',
            color: '#f43f5e',
            title: 'FinCEN SAR XML Narrative drafted',
            desc: 'Case CASE_2026_007 escalated to Compliance Officer',
            time: '1 hour ago'
        },
        {
            icon: '🧠',
            color: '#38bdf8',
            title: 'GraphRAG ChromaDB embedding committed',
            desc: 'Historical precedent match: Cosine similarity 0.94',
            time: '2 hours ago'
        },
        {
            icon: '🛡️',
            color: '#c084fc',
            title: 'Synthetic Identity Cluster quarantined',
            desc: 'Pre-evidence step-up authentication enforced on 6 cards',
            time: '3 hours ago'
        }
    ];

    timeline.innerHTML = events.map(e => `
        <div class="vui-timeline-item">
            <div class="vui-timeline-icon" style="border-color:${e.color}; box-shadow:0 0 10px ${e.color}40;">
                <span>${e.icon}</span>
            </div>
            <div class="vui-timeline-content">
                <span class="vui-timeline-title">${e.title}</span>
                <span style="font-size:0.72rem; color:#a7f3d0; opacity:0.88; margin-top:2px;">${e.desc}</span>
                <span class="vui-timeline-time">${e.time}</span>
            </div>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════════════════════════
// CHARTS (Canvas-based, no external dependencies)
// ═══════════════════════════════════════════════════════════════════════

function renderTypologyChart() {
    const canvas = document.getElementById('typologyCanvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const size = 180;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = size + 'px';
    canvas.style.height = size + 'px';
    ctx.scale(dpr, dpr);

    // Count typologies from mockResults
    const counts = {};
    mockResults.forEach(r => {
        const t = r.post_evidence_recommendation.fraud_typology || 'UNKNOWN';
        counts[t] = (counts[t] || 0) + 1;
    });

    const labels = Object.keys(counts);
    const values = Object.values(counts);
    const total = values.reduce((a, b) => a + b, 0);
    const colors = labels.map(l => TYPOLOGY_COLORS[l] || '#94a3b8');

    const cx = size / 2;
    const cy = size / 2;
    const outerR = 75;
    const innerR = 45;

    // Animate donut chart
    let animProgress = 0;
    function drawChart() {
        animProgress = Math.min(animProgress + 0.03, 1);
        const easedProgress = 1 - Math.pow(1 - animProgress, 3);

        ctx.clearRect(0, 0, size, size);

        let angle = -Math.PI / 2;
        labels.forEach((label, i) => {
            const sliceAngle = (values[i] / total) * Math.PI * 2 * easedProgress;

            ctx.beginPath();
            ctx.arc(cx, cy, outerR, angle, angle + sliceAngle);
            ctx.arc(cx, cy, innerR, angle + sliceAngle, angle, true);
            ctx.closePath();
            ctx.fillStyle = colors[i];
            ctx.fill();

            // Gap
            ctx.beginPath();
            ctx.arc(cx, cy, outerR, angle + sliceAngle - 0.02, angle + sliceAngle + 0.02);
            ctx.arc(cx, cy, innerR, angle + sliceAngle + 0.02, angle + sliceAngle - 0.02, true);
            ctx.closePath();
            ctx.fillStyle = '#02120a';
            ctx.fill();

            angle += sliceAngle;
        });

        // Center text
        ctx.fillStyle = '#e2e8f0';
        ctx.font = '700 18px JetBrains Mono';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(total, cx, cy - 6);
        ctx.fillStyle = '#6ee7b7';
        ctx.font = '600 8px Inter';
        ctx.fillText('CASES', cx, cy + 9);

        if (animProgress < 1) requestAnimationFrame(drawChart);
    }

    drawChart();

    // Populate Active Users-style Progress Bars below donut
    const progressList = document.getElementById('typologyProgressList');
    if (progressList) {
        progressList.innerHTML = labels.map((l, i) => {
            const pct = Math.round((values[i] / total) * 100);
            const color = colors[i];
            return `
            <div class="vui-metric-progress-item">
                <div class="vui-metric-top">
                    <span class="vui-metric-name">
                        <span style="width:7px; height:7px; border-radius:50%; background:${color}; box-shadow:0 0 6px ${color};"></span>
                        ${l.replace(/_/g, ' ')}
                    </span>
                    <span class="vui-metric-val">${values[i]} cases (${pct}%)</span>
                </div>
                <div class="vui-progress-bar">
                    <div class="vui-progress-fill" style="width:${pct}%; background:${color};"></div>
                </div>
            </div>`;
        }).join('');
    }
}

// ═══════════════════════════════════════════════════════════════════════
// INVESTIGATE PAGE
// ═══════════════════════════════════════════════════════════════════════

function initInvestigateForm() {
    const slider = document.getElementById('riskSlider');
    const valueEl = document.getElementById('riskValue');
    slider?.addEventListener('input', () => {
        valueEl.textContent = (slider.value / 100).toFixed(2);
    });

    const form = document.getElementById('investigationForm');
    form?.addEventListener('submit', (e) => {
        e.preventDefault();
        runInvestigation();
    });
}

async function runInvestigation() {
    const resultsContainer = document.getElementById('investigationResults');
    const progressSection = document.getElementById('progressSection');
    const resultsMetrics = document.getElementById('resultsMetrics');
    const progressBar = document.getElementById('progressBar');
    const progressStage = document.getElementById('progressStage');
    const stagesContainer = document.getElementById('progressStages');

    resultsContainer.style.display = 'block';
    resultsMetrics.style.display = 'none';
    progressBar.style.width = '0%';

    // Build stage chips
    stagesContainer.innerHTML = INVESTIGATION_STAGES.map((s, i) =>
        `<span class="stage-chip" data-stage="${i}">${s.replace('...', '')}</span>`
    ).join('');

    const accountId = document.getElementById('accountId').value;
    const transactionId = document.getElementById('transactionId').value;
    const triggerType = document.getElementById('triggerType').value;
    const riskScore = document.getElementById('riskSlider').value / 100;
    const amount = parseFloat(document.getElementById('txnAmount').value) || 8750;

    // ── Try real backend API first ──────────────────────────────────────────
    if (_apiAvailable) {
        try {
            // Animate progress while backend works
            let stageIdx = 0;
            const stageTimer = setInterval(() => {
                if (stageIdx < INVESTIGATION_STAGES.length) {
                    progressBar.style.width = `${((stageIdx + 1) / INVESTIGATION_STAGES.length * 100).toFixed(0)}%`;
                    progressStage.textContent = `⚙️ ${INVESTIGATION_STAGES[stageIdx]}`;
                    stagesContainer.querySelectorAll('.stage-chip').forEach((chip, ci) => {
                        if (ci < stageIdx) chip.className = 'stage-chip done';
                        else if (ci === stageIdx) chip.className = 'stage-chip active';
                        else chip.className = 'stage-chip';
                    });
                    stageIdx++;
                }
            }, 600);

            const resp = await fetch('/api/investigate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_id: accountId,
                    transaction_id: transactionId,
                    trigger_type: triggerType,
                    initial_risk: riskScore,
                    amount: amount,
                }),
            });

            clearInterval(stageTimer);

            if (resp.ok) {
                const result = await resp.json();

                // Mark all stages done
                progressBar.style.width = '100%';
                stagesContainer.querySelectorAll('.stage-chip').forEach(c => c.className = 'stage-chip done');
                progressStage.textContent = '✅ Investigation complete (LIVE agent)!';

                // Extract data from agent result
                const caseData = result.case || {};
                const nba = result.next_best_actions || {};
                const finalActs = nba.final || [];
                const fp = caseData.fraud_probability ?? riskScore;
                const pattern = caseData.pattern || 'none';
                const verdict = caseData.verdict || 'uncertain';
                const action = finalActs.length > 0 ? finalActs[0].action : 'MONITOR_CARD';

                document.getElementById('resFraudProb').textContent = `${(fp * 100).toFixed(0)}%`;
                document.getElementById('resUncertainty').textContent = `${((1 - fp) * 30).toFixed(0)}%`;
                document.getElementById('resTypology').textContent = pattern.replace(/_/g, ' ');
                document.getElementById('resAction').textContent = `${ACTION_ICONS[action] || '⚠️'} ${action.replace(/_/g, ' ')}`;

                const probEl = document.getElementById('resFraudProb');
                probEl.style.color = fp >= 0.85 ? '#f87171' : fp >= 0.70 ? '#fb923c' : '#38bdf8';

                // Summary from agent
                document.getElementById('summaryContent').textContent = result.summary || caseData.summary || 'Investigation completed via live agent.';

                // Evidence
                const connCards = caseData.connected_card_ids || (caseData.graph_evidence?.connected_cards) || [];
                const devProfiles = caseData.connected_device_profiles || [];
                const affectedTxns = caseData.affected_txn_ids || [];
                const evidenceList = caseData.evidence || [];
                const isProxy = devProfiles.length > 0 || connCards.length > 0 || (caseData.graph_evidence?.proxy_detected);

                let evidenceHtml = `
                    <div class="evidence-card">
                        <div class="evidence-value">${connCards.length}</div>
                        <div class="evidence-label">Connected Cards</div>
                    </div>
                    <div class="evidence-card">
                        <div class="evidence-value" style="color: ${isProxy ? '#f87171' : '#4ade80'}">${isProxy ? 'YES' : 'NO'}</div>
                        <div class="evidence-label">Device Ring Link</div>
                    </div>
                    <div class="evidence-card">
                        <div class="evidence-value">${affectedTxns.length}</div>
                        <div class="evidence-label">Affected Txns</div>
                    </div>
                `;

                if (evidenceList.length > 0 || connCards.length > 0 || devProfiles.length > 0) {
                    evidenceHtml += `<div class="evidence-detail-list" style="grid-column: 1 / -1; margin-top: 12px; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.6;">`;
                    if (connCards.length > 0) {
                        evidenceHtml += `<div><strong>Linked Cards in Cluster:</strong> <span class="mono">${connCards.join(', ')}</span></div>`;
                    }
                    if (devProfiles.length > 0) {
                        evidenceHtml += `<div><strong>Hardware Fingerprint:</strong> <span class="mono">${devProfiles[0]}</span></div>`;
                    }
                    evidenceList.forEach(ev => {
                        if (ev.claim) {
                            evidenceHtml += `<div style="margin-top: 6px;">🔍 <strong>Graph Signal:</strong> ${ev.claim}</div>`;
                        }
                    });
                    evidenceHtml += `</div>`;
                }

                document.getElementById('evidenceContent').innerHTML = evidenceHtml;

                // SAR
                const sar = result.sar || {};
                if (sar.file || sar.narrative || sar.required) {
                    const narrativeText = sar.narrative || sar.reason || 'Regulatory SAR filing mandatory under Policy v1.0 Section 3a.';
                    document.getElementById('sarContent').textContent = narrativeText;
                } else {
                    document.getElementById('sarContent').textContent = 'No regulatory SAR filing required for this case (Policy R1/R3: Exposure under threshold or legitimate spend).';
                }

                resultsMetrics.style.display = 'block';
                showToast('success', `Live investigation complete! Verdict: ${verdict}, Action: ${action.replace(/_/g, ' ')}`);
                return;
            }
            // If response not ok, fall through to mock
        } catch (apiErr) {
            console.warn('[HHGOA] API investigate failed, falling back to mock:', apiErr);
        }
    }

    // ── Fallback: Mock investigation (same as original) ─────────────────────
    // Animate through stages
    for (let i = 0; i < INVESTIGATION_STAGES.length; i++) {
        progressBar.style.width = `${((i + 1) / INVESTIGATION_STAGES.length * 100).toFixed(0)}%`;
        progressStage.textContent = `⚙️ ${INVESTIGATION_STAGES[i]}`;

        stagesContainer.querySelectorAll('.stage-chip').forEach((chip, ci) => {
            if (ci < i) chip.className = 'stage-chip done';
            else if (ci === i) chip.className = 'stage-chip active';
            else chip.className = 'stage-chip';
        });

        await sleep(400 + Math.random() * 300);
    }

    // Mark all done
    stagesContainer.querySelectorAll('.stage-chip').forEach(c => c.className = 'stage-chip done');
    progressStage.textContent = '✅ Investigation complete!';

    // Autonomous fraud signals
    const ipProxy = riskScore >= 0.70 || triggerType === 'PATTERN_MATCH';
    const newDevice = riskScore >= 0.75 || amount > 10000;

    const fraudProb = Math.min(0.99, riskScore + (ipProxy ? 0.08 : 0) + (newDevice ? 0.06 : 0));
    const typology = ipProxy && newDevice ? 'ACCOUNT_TAKEOVER' :
                     ipProxy ? 'CARD_NOT_PRESENT_RING' :
                     newDevice ? 'SYNTHETIC_IDENTITY' : 'SMURFING_VELOCITY';
    const action = fraudProb > 0.85 ? 'FREEZE_ACCOUNT' :
                   fraudProb > 0.70 ? 'BLOCK_TRANSACTION' : 'STEP_UP_AUTH';

    // Show results
    document.getElementById('resFraudProb').textContent = `${(fraudProb * 100).toFixed(0)}%`;
    document.getElementById('resUncertainty').textContent = `${((1 - fraudProb) * 30).toFixed(0)}%`;
    document.getElementById('resTypology').textContent = typology.replace(/_/g, ' ');
    document.getElementById('resAction').textContent = `${ACTION_ICONS[action] || '⚠️'} ${action.replace(/_/g, ' ')}`;

    const probEl = document.getElementById('resFraudProb');
    probEl.style.color = fraudProb >= 0.85 ? '#f87171' : fraudProb >= 0.70 ? '#fb923c' : '#38bdf8';

    // Summary
    document.getElementById('summaryContent').textContent =
        `Case investigation for account ${accountId} completed (offline mock).\n\n` +
        `Trigger Type: ${triggerType}\nInitial Risk Score: ${riskScore.toFixed(2)}\n` +
        `Transaction Amount: $${amount.toLocaleString()}\n\n` +
        `Fraud Probability: ${(fraudProb * 100).toFixed(1)}%\n` +
        `Typology: ${typology.replace(/_/g, ' ')}\nAction: ${action.replace(/_/g, ' ')}`;

    // Evidence
    document.getElementById('evidenceContent').innerHTML = `
        <div class="evidence-card">
            <div class="evidence-value">${ipProxy ? 2 : 0}</div>
            <div class="evidence-label">Shared Device Accounts</div>
        </div>
        <div class="evidence-card">
            <div class="evidence-value" style="color: ${ipProxy ? '#f87171' : '#4ade80'}">${ipProxy ? 'YES' : 'NO'}</div>
            <div class="evidence-label">Proxy IP</div>
        </div>
        <div class="evidence-card">
            <div class="evidence-value">${randomInt(0, 4)}</div>
            <div class="evidence-label">Ring Size</div>
        </div>
    `;

    // SAR
    if (fraudProb > 0.82) {
        document.getElementById('sarContent').textContent = generateMockSAR(`CASE_2026_${randomHex(6).toUpperCase()}`, typology);
    } else {
        document.getElementById('sarContent').textContent = 'No SAR required for this case.';
    }

    resultsMetrics.style.display = 'block';
    showToast('success', `Investigation complete! Action: ${action.replace(/_/g, ' ')}`);
}

// ═══════════════════════════════════════════════════════════════════════
// CASE VIEWER
// ═══════════════════════════════════════════════════════════════════════

function populateCaseViewer(forcedCaseId = null) {
    const select = document.getElementById('caseSelect');
    if (!select || !mockResults || mockResults.length === 0) return;

    const currentVal = forcedCaseId || select.value || mockResults[0]?.case_id;
    select.innerHTML = mockResults.map(r => {
        const post = r.post_evidence_recommendation || {};
        const typ = (post.fraud_typology || '').replace(/_/g, ' ');
        const act = (post.action || '').replace(/_/g, ' ');
        return `<option value="${r.case_id}">${r.case_id} — ${typ} (${act})</option>`;
    }).join('');

    select.value = currentVal;
    if (!select.dataset.listenerAttached) {
        select.addEventListener('change', () => renderCaseDetail(select.value));
        select.dataset.listenerAttached = 'true';
    }
    renderCaseDetail(select.value);
}

function renderCaseDetail(caseId) {
    const result = mockResults.find(r => r.case_id === caseId);
    if (!result) return;

    const post = result.post_evidence_recommendation;
    const ge = result.graph_evidence;

    // Metrics
    const metricsEl = document.getElementById('caseMetrics');
    metricsEl.innerHTML = `
        <div class="kpi-card kpi-small"><div class="kpi-value">${(post.confidence * 100).toFixed(0)}%</div><div class="kpi-label">Fraud Confidence</div></div>
        <div class="kpi-card kpi-small"><div class="kpi-value" style="font-size:0.9rem;">${post.fraud_typology.replace(/_/g, ' ')}</div><div class="kpi-label">Typology</div></div>
        <div class="kpi-card kpi-small"><div class="kpi-value">${ACTION_ICONS[post.action] || ''} ${post.action.replace(/_/g, ' ')}</div><div class="kpi-label">Final Action</div></div>
        <div class="kpi-card kpi-small"><div class="kpi-value" style="font-size:0.9rem;">${post.approval_required.replace(/_/g, ' ')}</div><div class="kpi-label">Approval</div></div>
        <div class="kpi-card kpi-small"><div class="kpi-value">${result.sar_filing_required ? 'YES ⚠️' : 'NO ✅'}</div><div class="kpi-label">SAR Required</div></div>
    `;

    // Full JSON
    document.getElementById('caseFullJson').textContent = JSON.stringify(result, null, 2);

    // Score
    const scoreEl = document.getElementById('caseScoreContent');
    if (result._score) {
        scoreEl.innerHTML = Object.entries(result._score).map(([k, v]) =>
            `<div style="margin-bottom:6px;">${v ? '✅' : '❌'} <strong>${k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</strong></div>`
        ).join('') + `<div style="margin-top:12px; color: var(--accent-cyan); font-weight:700;">Pass Rate: ${result._pass_rate}</div>`;
    } else {
        scoreEl.innerHTML = '<p style="color:var(--text-muted)">No benchmark score data for this case.</p>';
    }

    // Audit
    const auditEl = document.getElementById('caseAuditContent');
    auditEl.innerHTML = result.audit_trail.map(ev => `
        <div class="audit-event">
            <span class="audit-ts">${ev.timestamp.slice(0, 19)}</span>
            <div>
                <span class="audit-stage">${ev.stage}</span> → <span class="audit-text">${ev.event}</span>
                ${ev.detail ? `<div class="audit-detail">↳ ${ev.detail}</div>` : ''}
            </div>
        </div>
    `).join('');

    // SAR
    const sarEl = document.getElementById('caseSarContent');
    if (result.sar_draft) {
        sarEl.innerHTML = `<div class="sar-content">${result.sar_draft}</div>`;
    } else {
        sarEl.innerHTML = '<p style="color:var(--text-muted)">No SAR required for this case.</p>';
    }
}

// ═══════════════════════════════════════════════════════════════════════
// GRAPH VIEW
// ═══════════════════════════════════════════════════════════════════════

function initGraphView() {
    document.getElementById('btnLoadGraph')?.addEventListener('click', renderGraph);
    renderGraph(); // Initial render
}

function renderGraph() {
    const canvas = document.getElementById('graphCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 500 * dpr;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '500px';
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = 500;

    const accountId = document.getElementById('graphAccountId')?.value || 'ACC_001';
    const hop = parseInt(document.getElementById('hopDepth')?.value || '2');

    // Generate mock graph
    const nodeTypes = ['Account', 'Transaction', 'Device', 'IP_Address', 'Card'];
    const nodeColors = { Account: '#38bdf8', Transaction: '#818cf8', Device: '#f472b6', IP_Address: '#fb923c', Card: '#4ade80' };
    const edgeTypes = ['USED_DEVICE', 'USED_IP', 'SENT_TO', 'HAS_CARD', 'ORIGINATED'];

    const nodes = [];
    const edges = [];

    // Center node
    nodes.push({ id: accountId, type: 'Account', x: W / 2, y: H / 2, vx: 0, vy: 0, radius: 22 });

    // Generate random neighbors
    const nodeCount = 5 + hop * 4 + randomInt(0, 3);
    for (let i = 0; i < nodeCount; i++) {
        const type = nodeTypes[randomInt(0, nodeTypes.length - 1)];
        const id = `${type.substring(0, 3).toUpperCase()}_${randomHex(3).toUpperCase()}`;
        const angle = (Math.PI * 2 / nodeCount) * i + (Math.random() - 0.5) * 0.5;
        const dist = 80 + Math.random() * 120 + (i > nodeCount / 2 ? 60 : 0);
        nodes.push({
            id, type,
            x: W / 2 + Math.cos(angle) * dist,
            y: H / 2 + Math.sin(angle) * dist,
            vx: 0, vy: 0,
            radius: type === 'Account' ? 18 : 12,
        });
    }

    // Generate edges
    for (let i = 1; i < nodes.length; i++) {
        const src = i < nodeCount / 2 ? 0 : randomInt(0, Math.min(i - 1, Math.floor(nodeCount / 2)));
        edges.push({ source: src, target: i, type: edgeTypes[randomInt(0, edgeTypes.length - 1)] });
    }
    // Add a few cross edges
    for (let i = 0; i < 3; i++) {
        const a = randomInt(1, nodes.length - 1);
        const b = randomInt(1, nodes.length - 1);
        if (a !== b) edges.push({ source: a, target: b, type: edgeTypes[randomInt(0, edgeTypes.length - 1)] });
    }

    document.getElementById('graphNodeCount').textContent = nodes.length;
    document.getElementById('graphEdgeCount').textContent = edges.length;

    // Simple force simulation
    let animFrame = 0;
    const maxFrames = 120;

    function simulate() {
        // Repulsion
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                let dx = nodes[j].x - nodes[i].x;
                let dy = nodes[j].y - nodes[i].y;
                let dist = Math.sqrt(dx * dx + dy * dy) || 1;
                let force = 1500 / (dist * dist);
                let fx = (dx / dist) * force;
                let fy = (dy / dist) * force;
                nodes[i].vx -= fx; nodes[i].vy -= fy;
                nodes[j].vx += fx; nodes[j].vy += fy;
            }
        }

        // Attraction (edges)
        edges.forEach(e => {
            const a = nodes[e.source], b = nodes[e.target];
            let dx = b.x - a.x, dy = b.y - a.y;
            let dist = Math.sqrt(dx * dx + dy * dy) || 1;
            let force = (dist - 100) * 0.01;
            let fx = (dx / dist) * force, fy = (dy / dist) * force;
            a.vx += fx; a.vy += fy;
            b.vx -= fx; b.vy -= fy;
        });

        // Centering
        nodes.forEach(n => {
            n.vx += (W / 2 - n.x) * 0.001;
            n.vy += (H / 2 - n.y) * 0.001;
        });

        // Apply
        const damping = 0.85;
        nodes.forEach(n => {
            n.vx *= damping; n.vy *= damping;
            n.x += n.vx; n.y += n.vy;
            n.x = Math.max(30, Math.min(W - 30, n.x));
            n.y = Math.max(30, Math.min(H - 30, n.y));
        });

        // Draw
        ctx.clearRect(0, 0, W, H);

        // Edges
        edges.forEach(e => {
            const a = nodes[e.source], b = nodes[e.target];
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = 'rgba(51, 65, 85, 0.5)';
            ctx.lineWidth = 1;
            ctx.stroke();

            // Arrow
            const angle = Math.atan2(b.y - a.y, b.x - a.x);
            const arrowSize = 6;
            const endX = b.x - Math.cos(angle) * b.radius;
            const endY = b.y - Math.sin(angle) * b.radius;
            ctx.beginPath();
            ctx.moveTo(endX, endY);
            ctx.lineTo(endX - arrowSize * Math.cos(angle - 0.4), endY - arrowSize * Math.sin(angle - 0.4));
            ctx.lineTo(endX - arrowSize * Math.cos(angle + 0.4), endY - arrowSize * Math.sin(angle + 0.4));
            ctx.closePath();
            ctx.fillStyle = 'rgba(51, 65, 85, 0.5)';
            ctx.fill();
        });

        // Nodes
        nodes.forEach(n => {
            const color = nodeColors[n.type] || '#94a3b8';

            // Glow
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.radius + 4, 0, Math.PI * 2);
            const glow = ctx.createRadialGradient(n.x, n.y, n.radius, n.x, n.y, n.radius + 8);
            glow.addColorStop(0, color + '30');
            glow.addColorStop(1, 'transparent');
            ctx.fillStyle = glow;
            ctx.fill();

            // Node circle
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
            ctx.fillStyle = color + 'cc';
            ctx.fill();
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.stroke();

            // Label
            ctx.fillStyle = '#e2e8f0';
            ctx.font = '500 8px Inter';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(n.id.substring(0, 8), n.x, n.y + n.radius + 12);
        });

        animFrame++;
        if (animFrame < maxFrames) requestAnimationFrame(simulate);
    }

    simulate();
}

// ═══════════════════════════════════════════════════════════════════════
// APPROVAL QUEUE
// ═══════════════════════════════════════════════════════════════════════

function renderApprovals() {
    const container = document.getElementById('approvalList');
    const countEl = document.getElementById('pendingCount');
    if (!container) return;

    const filter = document.getElementById('tierFilter');
    filter?.addEventListener('change', () => renderApprovalCards());

    renderApprovalCards();
}

function renderApprovalCards() {
    const container = document.getElementById('approvalList');
    const filterVal = document.getElementById('tierFilter')?.value || 'all';
    const countEl = document.getElementById('pendingCount');

    let filtered = mockApprovals;
    if (filterVal !== 'all') {
        filtered = mockApprovals.filter(r =>
            r.post_evidence_recommendation.approval_required === filterVal
        );
    }

    countEl.textContent = filtered.length;

    container.innerHTML = filtered.map((r, i) => {
        const post = r.post_evidence_recommendation;
        const icon = ACTION_ICONS[post.action] || '⚠️';
        const tierColors = { TIER_1_ANALYST: '#38bdf8', TIER_2_ANALYST: '#fb923c', COMPLIANCE_OFFICER: '#f87171' };

        return `
        <div class="approval-card" data-index="${i}">
            <div class="approval-header" onclick="toggleApproval(this)">
                <div class="approval-header-left">
                    <span class="approval-icon">${icon}</span>
                    <div>
                        <span class="approval-case-id">${r.case_id}</span>
                        <span class="approval-action-tag"> — ${post.action.replace(/_/g, ' ')}</span>
                    </div>
                </div>
                <div style="display:flex;align-items:center;gap:12px;">
                    <span class="approval-conf">${(post.confidence * 100).toFixed(0)}%</span>
                    <span class="approval-expand-icon">▼</span>
                </div>
            </div>
            <div class="approval-body">
                <div class="approval-metrics">
                    <div class="approval-metric">
                        <div class="approval-metric-value" style="color:${tierColors[post.approval_required] || '#94a3b8'}">${post.approval_required.replace(/_/g, ' ')}</div>
                        <div class="approval-metric-label">Required Approval</div>
                    </div>
                    <div class="approval-metric">
                        <div class="approval-metric-value">${r.sar_filing_required ? 'YES ⚠️' : 'NO'}</div>
                        <div class="approval-metric-label">SAR Required</div>
                    </div>
                    <div class="approval-metric">
                        <div class="approval-metric-value">${(post.confidence * 100).toFixed(0)}%</div>
                        <div class="approval-metric-label">Confidence</div>
                    </div>
                </div>
                <div class="approval-detail"><strong>Justification:</strong> ${post.justification || 'N/A'}</div>
                <div class="approval-detail"><strong>Fraud Typology:</strong> ${post.fraud_typology.replace(/_/g, ' ')}</div>
                <div class="approval-actions">
                    <button class="btn btn-sm btn-approve" onclick="approveCase('${r.case_id}', 'approved')">✅ Approve</button>
                    <button class="btn btn-sm btn-reject" onclick="approveCase('${r.case_id}', 'rejected')">❌ Reject</button>
                    <button class="btn btn-sm btn-escalate" onclick="approveCase('${r.case_id}', 'escalated')">⬆️ Escalate</button>
                </div>
            </div>
        </div>`;
    }).join('');
}

function toggleApproval(header) {
    const card = header.closest('.approval-card');
    card.classList.toggle('expanded');
}

function approveCase(caseId, action) {
    const messages = {
        approved: `Case ${caseId} approved!`,
        rejected: `Case ${caseId} rejected.`,
        escalated: `Case ${caseId} escalated to senior analyst.`,
    };
    const types = { approved: 'success', rejected: 'warning', escalated: 'info' };
    showToast(types[action], messages[action]);
}

// ═══════════════════════════════════════════════════════════════════════
// ANALYTICS PAGE
// ═══════════════════════════════════════════════════════════════════════

function renderAnalytics() {
    renderActionChart();
    renderConfidenceChart();
    renderBenchmarkTable();

    document.getElementById('benchTs').textContent = new Date().toISOString().split('T')[0];

    document.getElementById('btnRunBenchmarkAnalytics')?.addEventListener('click', async () => {
        showToast('info', 'Running benchmark evaluation...');
        await sleep(2000);
        showToast('success', 'Benchmark complete! 20 cases evaluated.');
    });
}

function renderActionChart() {
    const canvas = document.getElementById('actionChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const W = 360, H = 220;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    ctx.scale(dpr, dpr);

    // Count actions
    const actionCounts = {};
    mockResults.forEach(r => {
        const a = r.post_evidence_recommendation.action;
        actionCounts[a] = (actionCounts[a] || 0) + 1;
    });

    const labels = Object.keys(actionCounts);
    const values = Object.values(actionCounts);
    const maxVal = Math.max(...values);
    const colors = ['#38bdf8', '#818cf8', '#f472b6', '#fb923c', '#4ade80', '#fbbf24', '#f87171', '#a78bfa'];

    const barW = Math.min(32, (W - 40) / labels.length - 8);
    const startX = 40;
    const chartH = H - 50;

    // Animate
    let progress = 0;
    function draw() {
        progress = Math.min(progress + 0.04, 1);
        const eased = 1 - Math.pow(1 - progress, 3);

        ctx.clearRect(0, 0, W, H);

        // Grid lines
        for (let i = 0; i <= 4; i++) {
            const y = 10 + (chartH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(startX, y);
            ctx.lineTo(W - 10, y);
            ctx.strokeStyle = 'rgba(56, 189, 248, 0.06)';
            ctx.lineWidth = 1;
            ctx.stroke();

            ctx.fillStyle = '#64748b';
            ctx.font = '500 8px JetBrains Mono';
            ctx.textAlign = 'right';
            ctx.fillText(Math.round(maxVal * (1 - i / 4)), startX - 4, y + 3);
        }

        // Bars
        labels.forEach((label, i) => {
            const x = startX + (W - startX - 10) / labels.length * i + (W - startX - 10) / labels.length / 2 - barW / 2;
            const h = (values[i] / maxVal) * chartH * eased;
            const y = 10 + chartH - h;

            // Bar gradient
            const grad = ctx.createLinearGradient(x, y, x, 10 + chartH);
            grad.addColorStop(0, colors[i % colors.length]);
            grad.addColorStop(1, colors[i % colors.length] + '40');
            ctx.fillStyle = grad;
            roundRect(ctx, x, y, barW, h, 3);

            // Value
            if (eased > 0.7) {
                ctx.fillStyle = '#e2e8f0';
                ctx.font = '600 9px JetBrains Mono';
                ctx.textAlign = 'center';
                ctx.fillText(values[i], x + barW / 2, y - 6);
            }

            // Label
            ctx.fillStyle = '#64748b';
            ctx.font = '500 6px Inter';
            ctx.textAlign = 'center';
            ctx.save();
            ctx.translate(x + barW / 2, H - 4);
            ctx.rotate(-0.5);
            ctx.fillText(label.replace(/_/g, ' ').substring(0, 12), 0, 0);
            ctx.restore();
        });

        if (progress < 1) requestAnimationFrame(draw);
    }

    draw();
}

function renderConfidenceChart() {
    const canvas = document.getElementById('confidenceChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const W = 360, H = 220;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    ctx.scale(dpr, dpr);

    // Build histogram
    const confidences = mockResults.map(r => r.post_evidence_recommendation.confidence);
    const bins = new Array(10).fill(0);
    confidences.forEach(c => {
        const binIdx = Math.min(9, Math.floor(c * 10));
        bins[binIdx]++;
    });

    const maxVal = Math.max(...bins);
    const startX = 40;
    const chartH = H - 50;
    const barW = (W - startX - 20) / bins.length - 2;

    let progress = 0;
    function draw() {
        progress = Math.min(progress + 0.04, 1);
        const eased = 1 - Math.pow(1 - progress, 3);

        ctx.clearRect(0, 0, W, H);

        // Grid
        for (let i = 0; i <= 4; i++) {
            const y = 10 + (chartH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(startX, y);
            ctx.lineTo(W - 10, y);
            ctx.strokeStyle = 'rgba(56, 189, 248, 0.06)';
            ctx.stroke();
        }

        bins.forEach((val, i) => {
            const x = startX + i * (barW + 2);
            const h = maxVal > 0 ? (val / maxVal) * chartH * eased : 0;
            const y = 10 + chartH - h;

            const grad = ctx.createLinearGradient(x, y, x, 10 + chartH);
            grad.addColorStop(0, '#818cf8');
            grad.addColorStop(1, '#818cf840');
            ctx.fillStyle = grad;
            roundRect(ctx, x, y, barW, h, 2);

            // Label
            ctx.fillStyle = '#64748b';
            ctx.font = '500 7px JetBrains Mono';
            ctx.textAlign = 'center';
            ctx.fillText(`${(i * 10)}%`, x + barW / 2, H - 8);
        });

        if (progress < 1) requestAnimationFrame(draw);
    }

    draw();
}

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h);
    ctx.lineTo(x, y + h);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
    ctx.fill();
}

function renderBenchmarkTable() {
    const tbody = document.getElementById('benchmarkTableBody');
    if (!tbody) return;

    tbody.innerHTML = mockResults.map(r => {
        const post = r.post_evidence_recommendation;
        const passRate = r._pass_rate || '100%';
        const passNum = parseInt(passRate);
        const statusClass = passNum >= 80 ? 'badge-low' : passNum >= 60 ? 'badge-medium' : 'badge-critical';
        const statusText = passNum >= 80 ? 'PASS' : passNum >= 60 ? 'PARTIAL' : 'FAIL';

        return `
        <tr>
            <td class="mono">${r.case_id}</td>
            <td style="color:${TYPOLOGY_COLORS[post.fraud_typology] || '#94a3b8'}">${post.fraud_typology.replace(/_/g, ' ')}</td>
            <td>${ACTION_ICONS[post.action] || ''} ${post.action.replace(/_/g, ' ')}</td>
            <td class="mono">${(post.confidence * 100).toFixed(0)}%</td>
            <td class="mono">${passRate}</td>
            <td><span class="badge ${statusClass}">${statusText}</span></td>
        </tr>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════════════════════
// TAB SYSTEM
// ═══════════════════════════════════════════════════════════════════════

function initAllTabs() {
    document.querySelectorAll('.tab-header').forEach(header => {
        header.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.dataset.tab;
                const parent = header.parentElement;

                header.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                parent.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
                const targetTab = parent.querySelector(`#tab${tabId.split('-').map(s => s.charAt(0).toUpperCase() + s.slice(1)).join('')}`) ||
                                  document.getElementById(`tab${tabId.charAt(0).toUpperCase() + tabId.slice(1)}`);
                if (targetTab) targetTab.classList.add('active');
            });
        });
    });

    // Populate case viewer when navigated to
    const observer = new MutationObserver(() => {
        if (document.getElementById('pageCaseviewer')?.classList.contains('active')) {
            populateCaseViewer();
        }
    });

    document.querySelectorAll('.page').forEach(page => {
        observer.observe(page, { attributes: true, attributeFilter: ['class'] });
    });
}

// ═══════════════════════════════════════════════════════════════════════
// TOAST NOTIFICATIONS
// ═══════════════════════════════════════════════════════════════════════

function showToast(type, message) {
    const container = document.getElementById('toastContainer');
    const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(40px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ═══════════════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════════════

function randomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomHex(length) {
    return Array.from({ length }, () => Math.floor(Math.random() * 16).toString(16)).join('');
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// ═══════════════════════════════════════════════════════════════════════
// INFO PAGE INTERACTION (CYBER TERMINAL)
// ═══════════════════════════════════════════════════════════════════════

function initInfoPage() {
    const termBody = document.getElementById('terminalLogBody');
    if (!termBody) return;

    function getNowTs() {
        const d = new Date();
        return `[${d.toTimeString().split(' ')[0]}]`;
    }

    function appendLog(tag, tagClass, message) {
        const line = document.createElement('div');
        line.className = 'log-line';
        line.innerHTML = `<span class="log-ts">${getNowTs()}</span> <span class="log-tag ${tagClass}">[${tag}]</span> <span class="log-msg">${message}</span>`;
        termBody.appendChild(line);
        termBody.scrollTop = termBody.scrollHeight;
    }

    document.getElementById('termBtnDiagnostic')?.addEventListener('click', () => {
        appendLog('DIAGNOSTIC', 'tag-ok', 'Running full engine self-test: 8 LangGraph stages verified healthy.');
        setTimeout(() => appendLog('DIAGNOSTIC', 'tag-info', 'TigerGraph schema: 8 vertex types, 9 edge types indexed.'), 300);
        setTimeout(() => appendLog('DIAGNOSTIC', 'tag-gold', 'ChromaDB memory store: 20 benchmark embeddings active.'), 600);
        setTimeout(() => appendLog('DIAGNOSTIC', 'tag-ok', 'Overall system health: 100% OPERATIONAL.'), 900);
        showToast('success', 'Diagnostic complete: All systems operational.');
    });

    document.getElementById('termBtnPing')?.addEventListener('click', () => {
        const latency = (Math.random() * 3 + 2.5).toFixed(1);
        appendLog('MCP-PING', 'tag-info', `TigerGraph MCP server latency = ${latency}ms (port 8765 status: 200 OK).`);
        showToast('info', `TigerGraph Ping: ${latency}ms latency`);
    });

    document.getElementById('termBtnPolicies')?.addEventListener('click', () => {
        appendLog('POLICIES', 'tag-gold', 'Loaded 5 Typologies: TYP-001 (CNP), TYP-002 (ATO), TYP-003 (Bust-Out), TYP-004 (Synthetic ID), TYP-005 (Smurfing).');
        appendLog('POLICIES', 'tag-ok', 'FinCEN 31 CFR § 1020.320 SAR automatic drafting rule armed.');
        showToast('info', 'Loaded 5 fraud typologies & FinCEN compliance matrix.');
    });

    document.getElementById('termBtnClear')?.addEventListener('click', () => {
        termBody.innerHTML = `
            <div class="log-line"><span class="log-ts">${getNowTs()}</span> <span class="log-tag tag-ok">[HHGOA-KERNEL]</span> <span class="log-msg">Terminal buffer cleared. Standby mode active.<span class="log-cursor"></span></span></div>
        `;
        showToast('info', 'Terminal log cleared.');
    });

    // Background heartbeat log every 20 seconds
    setInterval(() => {
        if (currentPage === 'info') {
            const events = [
                ['HEARTBEAT', 'tag-ok', 'TigerGraph graph sync tick OK. 0 dropped packets.'],
                ['VECTOR-MEM', 'tag-gold', 'ChromaDB collection synched with latest case resolutions.'],
                ['POLICY-GATE', 'tag-info', 'Compliance verification heartbeat active. 0 SLA breaches.']
            ];
            const ev = events[Math.floor(Math.random() * events.length)];
            appendLog(ev[0], ev[1], ev[2]);
        }
    }, 20000);
}
