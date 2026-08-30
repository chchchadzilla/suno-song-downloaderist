class SunoDownloaderist {
    constructor() {
        this.ws = null;
        this.isDownloading = false;
        this.subscriptionTier = 'Free';
        this.init();
    }

    async init() {
        this.bindEvents();
        await this.fetchStatus();
        await this.fetchSubscription();
        await this.updateLibraryCount();
        this.connectWebSocket();
    }

    bindEvents() {
        document.getElementById('apply-filters-btn').addEventListener('click', () => this.updateLibraryCount());
        document.getElementById('download-btn').addEventListener('click', () => this.startDownload());
        document.getElementById('pause-resume-btn').addEventListener('click', () => this.togglePause());
        document.getElementById('cancel-btn').addEventListener('click', () => this.cancelDownload());
        document.getElementById('select-all-btn').addEventListener('click', () => {
            document.getElementById('format-mp3').checked = true;
            if (this.subscriptionTier !== 'Free') {
                document.getElementById('format-wav').checked = true;
            }
            document.getElementById('format-mp4').checked = true;
        });
    }

    async fetchStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            const dot = document.getElementById('auth-status-dot');
            const text = document.getElementById('auth-status-text');
            
            if (data.authenticated) {
                dot.className = 'status-indicator green';
                text.textContent = 'Authenticated';
            } else {
                dot.className = 'status-indicator red';
                text.textContent = 'Not Authenticated';
            }
        } catch (e) {
            console.error('Failed to fetch status', e);
        }
    }

    async fetchSubscription() {
        try {
            const res = await fetch('/api/subscription');
            const data = await res.json();
            this.subscriptionTier = data.tier;
            document.getElementById('subscription-badge').textContent = this.subscriptionTier;
            
            if (this.subscriptionTier === 'Free') {
                const wavInput = document.getElementById('format-wav');
                const wavLabel = document.getElementById('format-wav-label');
                wavInput.disabled = true;
                wavInput.checked = false;
                wavLabel.classList.add('disabled');
            }
        } catch (e) {
            console.error('Failed to fetch subscription', e);
        }
    }

    getFilters() {
        return {
            liked_only: document.getElementById('filter-liked-only').checked,
            since: document.getElementById('filter-since').value || null,
            until: document.getElementById('filter-until').value || null,
            search: document.getElementById('filter-search').value || null,
            min_plays: parseInt(document.getElementById('filter-min-plays').value) || null
        };
    }

    async updateLibraryCount() {
        try {
            const filters = this.getFilters();
            const params = new URLSearchParams();
            for (const [k, v] of Object.entries(filters)) {
                if (v !== null && v !== false) params.append(k, v);
            }
            const res = await fetch(`/api/library/count?${params.toString()}`);
            const data = await res.json();
            
            document.getElementById('total-songs-text').textContent = `Library Size: ${data.count || 0}`;
            document.getElementById('filtered-count').textContent = `(${data.count || 0} match filters)`;
        } catch (e) {
            console.error('Failed to get library count', e);
        }
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/progress`);
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.updateProgress(data);
        };

        this.ws.onclose = () => {
            setTimeout(() => this.connectWebSocket(), 2000);
        };
    }

    updateProgress(data) {
        if (!data || !this.isDownloading) return;
        
        document.getElementById('progress-count').textContent = `${data.completed || 0} of ${data.total || 0} songs`;
        
        let percentage = 0;
        if (data.total > 0) {
            percentage = Math.round(((data.completed || 0) / data.total) * 100);
        }
        
        document.getElementById('progress-percentage').textContent = `${percentage}%`;
        document.getElementById('progress-bar-fill').style.width = `${percentage}%`;
        
        if (data.current_file) {
            document.getElementById('current-file-text').textContent = `Downloading: ${data.current_file}`;
        }
        
        if (data.status === 'completed' || data.status === 'cancelled') {
            this.isDownloading = false;
            document.getElementById('progress-panel').classList.add('hidden');
            document.getElementById('results-panel').classList.remove('hidden');
            document.getElementById('result-downloaded').textContent = data.completed || 0;
            document.getElementById('result-failed').textContent = data.failed || 0;
        }
    }

    async startDownload() {
        const formats = [];
        if (document.getElementById('format-mp3').checked) formats.push('mp3');
        if (document.getElementById('format-wav').checked) formats.push('wav');
        if (document.getElementById('format-mp4').checked) formats.push('mp4');
        
        const output_dir = document.getElementById('output-dir').value || '~/Music/SunoDownloaderist/';
        
        const options = {
            formats: formats,
            filters: this.getFilters(),
            output_dir: output_dir
        };

        try {
            const res = await fetch('/api/download/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(options)
            });
            
            if (res.ok) {
                this.isDownloading = true;
                document.getElementById('progress-panel').classList.remove('hidden');
                document.getElementById('results-panel').classList.add('hidden');
            }
        } catch (e) {
            console.error('Failed to start download', e);
        }
    }

    async togglePause() {
        const btn = document.getElementById('pause-resume-btn');
        const action = btn.textContent === 'Pause' ? 'pause' : 'resume';
        
        try {
            const res = await fetch(`/api/download/${action}`, { method: 'POST' });
            if (res.ok) {
                btn.textContent = action === 'pause' ? 'Resume' : 'Pause';
            }
        } catch (e) {
            console.error(`Failed to ${action} download`, e);
        }
    }

    async cancelDownload() {
        try {
            await fetch('/api/download/cancel', { method: 'POST' });
            this.isDownloading = false;
            document.getElementById('progress-panel').classList.add('hidden');
        } catch (e) {
            console.error('Failed to cancel download', e);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.app = new SunoDownloaderist();
});
