let currentPlatform = 'naver';
let currentEventSource = null;

const PLATFORM_CONFIG = {
    naver: { label: '블로그 ID', placeholder: '예: akzkfltm2', hint: 'URL의 blog.naver.com/ 뒤 부분' },
    youtube: { label: '채널 핸들', placeholder: '예: @channelname', hint: '@핸들 또는 채널 ID (UC로 시작)' },
    instagram: { label: '사용자명', placeholder: '예: username', hint: '인스타그램 사용자명 (@없이)' },
    threads: { label: '사용자명', placeholder: '예: username', hint: '스레드 사용자명' },
    x: { label: '사용자명', placeholder: '예: username', hint: 'X(트위터) 사용자명 (@없이)' },
    tiktok: { label: '사용자명', placeholder: '예: username', hint: '틱톡 사용자명 (@없이)' },
};

function switchTab(platform) {
    if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
    }
    currentPlatform = platform;
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.platform === platform);
    });
    const cfg = PLATFORM_CONFIG[platform];
    document.getElementById('inputLabel').textContent = cfg.label;
    document.getElementById('accountId').placeholder = cfg.placeholder;
    document.getElementById('inputHint').textContent = cfg.hint;
    document.getElementById('accountId').value = '';
    document.getElementById('results').style.display = 'none';
    document.getElementById('error').style.display = 'none';
    document.getElementById('loading').style.display = 'none';
}

function startAnalysis() {
    const accountId = document.getElementById('accountId').value.trim();
    if (!accountId) {
        showError('ID를 입력해주세요.');
        return;
    }

    if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
    }

    const btn = document.getElementById('analyzeBtn');
    btn.disabled = true;
    btn.querySelector('.btn-text').style.display = 'none';
    btn.querySelector('.btn-loading').style.display = 'inline';

    document.getElementById('loading').style.display = 'block';
    document.getElementById('results').style.display = 'none';
    document.getElementById('error').style.display = 'none';

    showProgress(0, 0, '분석 준비 중...');

    const params = new URLSearchParams({ platform: currentPlatform, id: accountId });
    const es = new EventSource(`/api/analyze/stream?${params}`);
    currentEventSource = es;
    let gotResult = false;

    es.onmessage = function(event) {
        const data = JSON.parse(event.data);

        if (data.type === 'progress') {
            showProgress(data.current, data.total, data.message);
        } else if (data.type === 'result') {
            gotResult = true;
            renderResult(data.data, data.analyzed_at);
            cleanup();
        } else if (data.type === 'error') {
            showError(data.message);
            cleanup();
        } else if (data.type === 'done') {
            cleanup();
        }
    };

    es.onerror = function() {
        if (!gotResult) {
            showError('서버 연결이 끊어졌습니다. 다시 시도해주세요.');
        }
        cleanup();
    };

    function cleanup() {
        es.close();
        currentEventSource = null;
        btn.disabled = false;
        btn.querySelector('.btn-text').style.display = 'inline';
        btn.querySelector('.btn-loading').style.display = 'none';
        document.getElementById('loading').style.display = 'none';
    }
}

function showProgress(current, total, message) {
    const loadingText = document.getElementById('loadingText');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');
    const progressDetail = document.getElementById('progressDetail');

    loadingText.textContent = message;

    if (total > 0) {
        const pct = Math.round((current / total) * 100);
        progressBar.style.display = 'block';
        progressFill.style.width = pct + '%';
        progressDetail.textContent = `${current.toLocaleString()} / ${total.toLocaleString()}건 (${pct}%)`;
        progressDetail.style.display = 'block';
    } else {
        progressBar.style.display = 'none';
        progressDetail.style.display = 'none';
    }
}

function showError(msg) {
    const el = document.getElementById('error');
    el.textContent = msg;
    el.style.display = 'block';
}

function renderResult(r, analyzedAt) {
    document.getElementById('results').style.display = 'block';
    const cardsEl = document.getElementById('blogCards');
    cardsEl.innerHTML = '';
    cardsEl.appendChild(createCard(r));
}

function createCard(r) {
    const card = document.createElement('div');
    card.className = 'blog-card';
    const q = r.quality;
    const scorePercent = Math.min(q.score, 100);
    const info = r.info;
    const isLimited = r.limited === true;

    // Stats grid based on platform
    let statsHtml = '';
    if (r.platform === 'naver') {
        statsHtml = `
            <div class="stat-item"><div class="stat-value">${(info.posts || 0).toLocaleString()}</div><div class="stat-label">총 게시글</div></div>
            <div class="stat-item"><div class="stat-value">${r.freq.avg_per_week || 0}</div><div class="stat-label">주간 포스팅</div></div>
            <div class="stat-item"><div class="stat-value">${r.freq.last_post_days_ago != null ? r.freq.last_post_days_ago + '일' : '-'}</div><div class="stat-label">마지막 포스팅</div></div>
        `;
    } else if (r.platform === 'youtube') {
        statsHtml = `
            <div class="stat-item"><div class="stat-value">${info.subscribers || '-'}</div><div class="stat-label">구독자</div></div>
            <div class="stat-item"><div class="stat-value">${(info.videos || 0).toLocaleString()}</div><div class="stat-label">총 영상</div></div>
            <div class="stat-item"><div class="stat-value">${r.freq.last_post_days_ago != null ? r.freq.last_post_days_ago + '일' : '-'}</div><div class="stat-label">마지막 업로드</div></div>
        `;
    } else if (r.platform === 'tiktok' && !isLimited) {
        statsHtml = `
            <div class="stat-item"><div class="stat-value">${info.followers ? info.followers.toLocaleString() : '-'}</div><div class="stat-label">팔로워</div></div>
            <div class="stat-item"><div class="stat-value">${info.videos ? info.videos.toLocaleString() : '-'}</div><div class="stat-label">총 영상</div></div>
            <div class="stat-item"><div class="stat-value">${info.total_likes ? info.total_likes.toLocaleString() : '-'}</div><div class="stat-label">총 좋아요</div></div>
        `;
    }

    // Search exposure summary
    let exposureHtml = '';
    if (r.search_results && r.search_results.length > 0) {
        const exposed = r.search_results.filter(s => s.exposed === true).length;
        const notExposed = r.search_results.filter(s => s.exposed === false).length;
        const total = exposed + notExposed;
        const rate = total > 0 ? Math.round(exposed / total * 100) : 0;
        const rateColor = rate >= 80 ? 'var(--success)' : rate >= 50 ? 'var(--warning)' : 'var(--danger)';

        exposureHtml = `
            <div class="card-section">
                <h4>검색 노출 테스트 (${total}건)</h4>
                <div class="exposure-summary">
                    <div class="exposure-rate" style="color: ${rateColor}">${rate}%</div>
                    <div class="exposure-detail">노출 ${exposed}건 / 미노출 ${notExposed}건</div>
                </div>
                <ul class="search-list">
                    ${r.search_results.map(s => `
                        <li>
                            <div class="search-title">${escapeHtml(s.title)}</div>
                            <div class="search-status ${s.exposed === true ? 'exposed' : s.exposed === false ? 'not-exposed' : 'unknown'}">
                                ${s.exposed === true ? '노출' : s.exposed === false ? '미노출' : '확인불가'}
                            </div>
                        </li>
                    `).join('')}
                </ul>
            </div>
        `;
    }

    // Posts list
    let postsHtml = '';
    if (r.posts && r.posts.length > 0) {
        const postLabel = r.platform === 'youtube' ? '최근 영상' : '최근 게시글';
        postsHtml = `
            <div class="card-section">
                <h4>${postLabel}</h4>
                <ul class="post-list">
                    ${r.posts.map(p => `
                        <li>
                            <span class="post-date">${(p.date || '').substring(0, 10)}</span>
                            <span class="post-title">${escapeHtml(p.title)}</span>
                            ${p.views != null ? `<span class="post-views">${p.views.toLocaleString()}회</span>` : ''}
                        </li>
                    `).join('')}
                </ul>
            </div>
        `;
    }

    // Limited platform banner
    let limitedHtml = '';
    if (isLimited) {
        limitedHtml = `
            <div class="limited-banner">
                <h4>제한적 분석</h4>
                <p>이 플랫폼은 서버사이드 크롤링이 제한되어 일부 데이터만 표시됩니다.<br>공식 API 연동 시 상세 분석이 가능합니다.</p>
            </div>
        `;
    }

    card.innerHTML = `
        <div class="card-header">
            <div class="card-header-left">
                <h3>${escapeHtml(info.name || r.id)}</h3>
                <div class="blog-id">
                    <a href="${r.url}" target="_blank">${r.id}</a>
                </div>
            </div>
            <span class="badge ${q.level}">${q.level_text}</span>
        </div>
        <div class="card-body">
            ${limitedHtml}

            <div class="score-gauge ${q.level}">
                <div class="score-number">${q.score}</div>
                <div class="score-label">저품질 위험 점수</div>
                <div class="score-bar">
                    <div class="score-bar-fill" style="width: ${scorePercent}%"></div>
                </div>
            </div>

            ${statsHtml ? `<div class="stats-grid">${statsHtml}</div>` : ''}

            <div class="card-section">
                <h4>분석 결과</h4>
                <ul class="reason-list">
                    ${q.reasons.map(reason => `
                        <li class="${reason.type}">
                            <span>${reason.type === 'success' ? '+' : reason.type === 'warning' ? '!' : '-'}</span>
                            ${escapeHtml(reason.text)}
                        </li>
                    `).join('')}
                </ul>
            </div>

            ${exposureHtml}
            ${postsHtml}

            ${q.suggestions && q.suggestions.length > 0 ? `
                <div class="card-section">
                    <h4>개선 제안</h4>
                    <ul class="suggestion-list">
                        ${q.suggestions.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}

            ${r.freq && r.freq.post_dates && r.freq.post_dates.length > 0 ? `
                <div class="card-section">
                    <h4>활동 빈도</h4>
                    <div class="chart-container">
                        <canvas id="chart-0"></canvas>
                    </div>
                </div>
            ` : ''}
        </div>
    `;

    setTimeout(() => renderChart(r), 100);
    return card;
}

function renderChart(r) {
    const canvas = document.getElementById('chart-0');
    if (!canvas || !r.freq || !r.freq.post_dates || r.freq.post_dates.length === 0) return;

    const dateCounts = {};
    r.freq.post_dates.forEach(d => { dateCounts[d] = (dateCounts[d] || 0) + 1; });

    const sorted = Object.keys(dateCounts).sort();
    const labels = sorted.map(d => d.substring(5));
    const values = sorted.map(d => dateCounts[d]);

    const color = r.quality.level === 'success' ? 'rgba(91, 154, 109, 0.7)' :
        r.quality.level === 'warning' ? 'rgba(212, 161, 71, 0.7)' : 'rgba(196, 113, 91, 0.7)';

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{ label: '게시글', data: values, backgroundColor: color, borderRadius: 4 }]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { color: '#8B7265', font: { size: 11 } }, grid: { display: false } },
                y: { ticks: { color: '#8B7265', stepSize: 1 }, grid: { color: 'rgba(0,0,0,0.04)' }, beginAtZero: true },
            }
        }
    });
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('accountId').addEventListener('keydown', e => {
        if (e.key === 'Enter') startAnalysis();
    });
});
