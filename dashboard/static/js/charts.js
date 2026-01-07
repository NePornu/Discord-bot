// Ultimate Chart.js Configuration - Premium Charts with Gradients

// Create gradient for chart
function createGradient(ctx, color1, color2) {
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, color1);
    gradient.addColorStop(1, color2);
    return gradient;
}

// Premium Chart Defaults
Chart.defaults.color = '#a1a1aa';
Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.1)';
Chart.defaults.font.family = 'Inter, sans-serif';

// Common chart options with premium styling
const premiumChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
        mode: 'index',
        intersect: false,
    },
    plugins: {
        legend: {
            labels: {
                usePointStyle: true,
                padding: 15,
                font: {
                    size: 12,
                    weight: '600'
                }
            }
        },
        tooltip: {
            backgroundColor: 'rgba(0, 0, 0, 0.8)',
            padding: 12,
            cornerRadius: 8,
            titleFont: {
                size: 14,
                weight: '600'
            },
            bodyFont: {
                size: 13
            },
            borderColor: 'rgba(139, 92, 246, 0.5)',
            borderWidth: 1
        }
    },
    scales: {
        x: {
            grid: {
                color: 'rgba(255, 255, 255, 0.05)',
                drawBorder: false
            },
            ticks: {
                font: {
                    size: 11,
                    weight: '500'
                }
            }
        },
        y: {
            grid: {
                color: 'rgba(255, 255, 255, 0.05)',
                drawBorder: false
            },
            ticks: {
                font: {
                    size: 11,
                    weight: '500'
                }
            },
            beginAtZero: true
        }
    },
    animation: {
        duration: 1500,
        easing: 'easeInOutQuart'
    }
};

// Create line chart with gradient
function createLineChart(canvasId, labels, data, label, color1 = '#8b5cf6', color2 = '#ec4899') {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const gradient = createGradient(ctx, color1, color2);

    // Fallback for empty data
    if (!data || data.length === 0 || data.every(v => v === 0)) {
        ctx.font = '14px Inter';
        ctx.fillStyle = '#71717a';
        ctx.textAlign = 'center';
        ctx.fillText('📊 Collecting data...', ctx.canvas.width / 2, ctx.canvas.height / 2);
        return null;
    }

    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: data,
                borderColor: gradient,
                backgroundColor: `${color1}20`,
                borderWidth: 3,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: gradient,
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6
            }]
        },
        options: { ...premiumChartOptions }
    });
}

// Create bar chart with gradient
function createBarChart(canvasId, labels, data, label, color1 = '#8b5cf6', color2 = '#ec4899') {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const gradient = createGradient(ctx, color1, color2);

    if (!data || data.length === 0 || data.every(v => v === 0)) {
        ctx.font = '14px Inter';
        ctx.fillStyle = '#71717a';
        ctx.textAlign = 'center';
        ctx.fillText('📊 Collecting data...', ctx.canvas.width / 2, ctx.canvas.height / 2);
        return null;
    }

    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: data,
                backgroundColor: gradient,
                borderRadius: 8,
                borderSkipped: false
            }]
        },
        options: { ...premiumChartOptions }
    });
}

// Create multi-dataset chart
function createMultiChart(canvasId, labels, datasets) {
    const ctx = document.getElementById(canvasId).getContext('2d');

    const colors = [
        { primary: '#8b5cf6', secondary: '#a78bfa' },
        { primary: '#ec4899', secondary: '#f472b6' },
        { primary: '#10b981', secondary: '#34d399' },
        { primary: '#f59e0b', secondary: '#fbbf24' }
    ];

    const formattedDatasets = datasets.map((dataset, i) => {
        const colorScheme = colors[i % colors.length];
        const gradient = createGradient(ctx, colorScheme.primary, colorScheme.secondary);

        return {
            label: dataset.label,
            data: dataset.data,
            borderColor: gradient,
            backgroundColor: `${colorScheme.primary}30`,
            borderWidth: 3,
            fill: true,
            tension: 0.4
        };
    });

    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: formattedDatasets
        },
        options: { ...premiumChartOptions }
    });
}

// Animated counter
function animateValue(element, start, end, duration) {
    const range = end - start;
    const increment = range / (duration / 16);
    let current = start;

    const timer = setInterval(() => {
        current += increment;
        if ((increment > 0 && current >= end) || (increment < 0 && current <= end)) {
            current = end;
            clearInterval(timer);
        }
        element.textContent = Math.round(current).toLocaleString();
    }, 16);
}

// Show loading skeleton
function showSkeleton(container) {
    container.innerHTML = '<div class="skeleton" style="height: 100%; border-radius: 12px;"></div>';
}

// Format number with suffix
function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

// Export utilities
window.ChartUtils = {
    createLineChart,
    createBarChart,
    createMultiChart,
    animateValue,
    showSkeleton,
    formatNumber,
    premiumChartOptions
};
