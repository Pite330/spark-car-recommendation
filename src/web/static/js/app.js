const form = document.querySelector('#recommend-form');
const resultsSection = document.querySelector('#results-section');
const recommendationsGrid = document.querySelector('#recommendation-grid');
const resultSummary = document.querySelector('#result-summary');
const relaxedNote = document.querySelector('#relaxed-note');
const compareButton = document.querySelector('#compare-button');
const compareCount = document.querySelector('#compare-count');
const comparisonSection = document.querySelector('#comparison-section');
const comparisonTable = document.querySelector('#comparison-table');
const selectedCars = new Set();
let latestRecommendations = [];
let compareChart = null;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
}

function toast(message) {
  const element = document.querySelector('#toast');
  element.textContent = message;
  element.classList.add('show');
  window.setTimeout(() => element.classList.remove('show'), 2400);
}

function displayPrice(car) {
  const min = Number(car.price_min_wan).toFixed(2);
  const max = Number(car.price_max_wan ?? car.price_min_wan).toFixed(2);
  return min === max ? `${min} 万` : `${min}—${max} 万`;
}

function displaySales(car) {
  if (car.sales === null || car.sales === undefined || car.sales === '') return '月销量暂无数据';
  const period = car.sales_period ? `${car.sales_period} · ` : '';
  return `${period}月销量 ${Number(car.sales).toLocaleString('zh-CN')} 辆`;
}

function recommendationCard(car, index) {
  const tags = [car.body_type, car.energy_type, car.seats ? `${car.seats} 座` : null]
    .filter(Boolean).map((tag) => `<span>${escapeHtml(tag)}</span>`).join('');
  return `
    <article class="recommendation-card ${index === 0 ? 'top' : ''}">
      <div class="card-rank"><span>NO. ${String(index + 1).padStart(2, '0')}</span><div class="score-ring" style="--score:${car.score}" data-score="${car.score}"></div></div>
      <span class="card-brand">${escapeHtml(car.brand)}</span>
      <h3>${escapeHtml(car.model_name)}</h3>
      <p class="car-price"><strong>${escapeHtml(displayPrice(car))}</strong> · 参考起售价</p>
      <p class="car-sales">${escapeHtml(displaySales(car))}</p>
      <div class="tags">${tags}</div>
      <p class="reason">${escapeHtml(car.reason)}</p>
      <div class="card-footer">
        <span class="reason-source">${car.reason_source === 'llm' ? (car.reason_provider === 'deepseek' ? 'DeepSeek 改写' : '模型改写') : '规则生成'}</span>
        <label class="compare-toggle"><input type="checkbox" data-car-id="${escapeHtml(car.car_id)}"> 加入对比</label>
      </div>
    </article>`;
}

function updateCompareState() {
  compareCount.textContent = selectedCars.size;
  compareButton.disabled = selectedCars.size < 2 || selectedCars.size > 3;
}

recommendationsGrid.addEventListener('change', (event) => {
  const checkbox = event.target.closest('input[data-car-id]');
  if (!checkbox) return;
  if (checkbox.checked && selectedCars.size >= 3) {
    checkbox.checked = false;
    toast('最多选择 3 款车型');
    return;
  }
  checkbox.checked ? selectedCars.add(checkbox.dataset.carId) : selectedCars.delete(checkbox.dataset.carId);
  updateCompareState();
});

form?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const payload = {
    budget_min_wan: Number(data.get('budget_min_wan')),
    budget_max_wan: Number(data.get('budget_max_wan')),
    body_type: data.get('body_type'),
    energy_type: data.get('energy_type'),
    brands: data.get('brand') ? [data.get('brand')] : [],
    scenario: data.get('scenario'),
    min_seats: data.get('min_seats') ? Number(data.get('min_seats')) : null,
    min_sales: data.get('min_sales') ? Number(data.get('min_sales')) : null,
    limit: 5,
    use_llm: data.get('use_llm') === 'on'
  };

  form.classList.add('loading');
  form.querySelector('button[type="submit"]').disabled = true;
  try {
    const response = await fetch('/api/recommend', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || '推荐请求失败');

    latestRecommendations = body.recommendations;
    selectedCars.clear();
    updateCompareState();
    comparisonSection.classList.add('is-hidden');
    recommendationsGrid.innerHTML = latestRecommendations.map(recommendationCard).join('');
    resultSummary.textContent = body.total_candidates
      ? `候选 ${body.total_candidates} 款，按匹配分从高到低排序。`
      : '无符合条件的车型。';
    relaxedNote.classList.toggle('is-hidden', body.relaxed_conditions.length === 0);
    relaxedNote.textContent = body.relaxed_conditions.length
      ? `候选不足，已放宽：${body.relaxed_conditions.join('；')}` : '';
    if (!latestRecommendations.length) {
      recommendationsGrid.innerHTML = '<div class="alert warning">请扩大预算，或减少车身 / 能源限制后重试。</div>';
    }
    resultsSection.classList.remove('is-hidden');
    resultsSection.scrollIntoView({behavior: 'smooth', block: 'start'});
  } catch (error) {
    toast(error.message);
  } finally {
    form.classList.remove('loading');
    form.querySelector('button[type="submit"]').disabled = false;
  }
});

const comparisonRows = [
  ['车型', 'model_name', (v) => v],
  ['品牌', 'brand', (v) => v],
  ['参考价格', 'price_min_wan', (v, car) => displayPrice(car)],
  ['在售配置数', 'trim_count', (v) => `${v} 款`],
  ['车身类型', 'body_type', (v) => v],
  ['能源类型', 'energy_type', (v) => v],
  ['月销量', 'sales', (v) => `${Number(v).toLocaleString('zh-CN')} 辆`],
  ['销量周期', 'sales_period', (v) => v],
  ['座位数', 'seats', (v) => `${v} 座`],
  ['续航', 'range_km', (v) => `${Number(v).toFixed(0)} km`],
  ['标注功率', 'horsepower', (v) => `${v} hp`],
  ['车型年款', 'model_year', (v) => v]
];

function renderComparison(cars) {
  comparisonTable.innerHTML = comparisonRows
    .filter(([, key]) => cars.some((car) => car[key] != null))
    .map(([label, key, formatter]) => `<tr><th>${label}</th>${cars.map((car) => `<td>${car[key] == null ? '—' : escapeHtml(formatter(car[key], car))}</td>`).join('')}</tr>`)
    .join('');

  if (!window.echarts) return;
  if (compareChart) compareChart.dispose();
  compareChart = echarts.init(document.querySelector('#comparison-chart'));
  const modelNames = cars.map((car) => car.model_name);
  const priceValues = cars.map((car) => Number(car.price_min_wan));
  const salesValues = cars.map((car) => car.sales == null
    ? {value: 0, missing: true, itemStyle: {opacity: 0}}
    : {value: Number(car.sales), missing: false});

  compareChart.setOption({
    color: ['#176246', '#e56f3a'],
    animationDuration: 520,
    animationEasing: 'cubicOut',
    tooltip: {
      trigger: 'axis',
      axisPointer: {type: 'shadow'},
      backgroundColor: 'rgba(25, 39, 32, .96)',
      borderWidth: 0,
      padding: [12, 14],
      textStyle: {color: '#fffef8', fontSize: 12, lineHeight: 21},
      formatter: (params) => {
        const car = cars[params[0].dataIndex];
        const sales = car.sales == null ? '暂无' : `${Number(car.sales).toLocaleString('zh-CN')} 辆`;
        return `<strong>${escapeHtml(car.model_name)}</strong><br>参考起售价　${formatDecimal(car.price_min_wan, 2)} 万元<br>同期月销量　${sales}`;
      }
    },
    legend: {
      orient: 'horizontal', left: 'center', top: 10,
      icon: 'roundRect', itemWidth: 18, itemHeight: 7, itemGap: 22,
      textStyle: {color: '#4f5f56', fontSize: 11, fontWeight: 600}
    },
    grid: {left: 62, right: 66, top: 62, bottom: 74},
    xAxis: {
      type: 'category',
      data: modelNames,
      axisTick: {show: false},
      axisLine: {lineStyle: {color: 'rgba(27,94,68,.18)'}},
      axisLabel: {
        interval: 0, color: '#4f5f56', fontSize: 11, fontWeight: 600,
        width: 95, overflow: 'truncate', margin: 16
      }
    },
    yAxis: [
      {
        type: 'value', name: '万元', min: 0, splitNumber: 4,
        nameTextStyle: {color: '#65736b', padding: [0, 0, 8, 0]},
        axisLabel: {color: '#7b8780', formatter: '{value}'},
        splitLine: {lineStyle: {color: 'rgba(27,94,68,.09)'}}
      },
      {
        type: 'value', name: '辆 / 月', min: 0, splitNumber: 4,
        nameTextStyle: {color: '#65736b', padding: [0, 0, 8, 0]},
        axisLabel: {color: '#7b8780', formatter: (value) => Number(value).toLocaleString('zh-CN')},
        splitLine: {show: false}
      }
    ],
    series: [
      {
        name: '参考起售价', type: 'bar', yAxisIndex: 0, data: priceValues,
        barMaxWidth: 34, barGap: '28%',
        itemStyle: {borderRadius: [8, 8, 2, 2]},
        label: {show: true, position: 'top', color: '#176246', fontSize: 10, fontWeight: 700, formatter: ({value}) => `${formatDecimal(value, 2)} 万`}
      },
      {
        name: '同期月销量', type: 'bar', yAxisIndex: 1, data: salesValues,
        barMaxWidth: 34,
        itemStyle: {borderRadius: [8, 8, 2, 2]},
        label: {
          show: true, position: 'top', color: '#c65e30', fontSize: 10, fontWeight: 700,
          formatter: ({data, value}) => data.missing ? '暂无' : Number(value).toLocaleString('zh-CN')
        }
      }
    ]
  });
}

compareButton.addEventListener('click', async () => {
  try {
    const response = await fetch('/api/compare', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({car_ids: [...selectedCars]})});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || '车型对比失败');
    comparisonSection.classList.remove('is-hidden');
    window.requestAnimationFrame(() => {
      renderComparison(body.cars);
      comparisonSection.scrollIntoView({behavior: 'smooth'});
    });
  } catch (error) { toast(error.message); }
});

document.querySelector('#close-comparison').addEventListener('click', () => comparisonSection.classList.add('is-hidden'));

function renderCatalogCharts() {
  if (!window.echarts) return;
  const energyChart = echarts.init(document.querySelector('#energy-chart'));
  energyChart.setOption({
    color: ['#1b5e44', '#d8ff63', '#ff7a3d', '#6e9d89', '#b8c5bc'],
    tooltip: {trigger: 'item'},
    series: [{
      type: 'pie',
      radius: ['39%', '61%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: true,
      minShowLabelAngle: 1,
      itemStyle: {borderColor: '#f4f4ed', borderWidth: 3, borderRadius: 5},
      label: {
        show: true,
        position: 'outside',
        alignTo: 'edge',
        edgeDistance: 8,
        bleedMargin: 2,
        color: '#637068',
        fontSize: 11,
        formatter: '{b}'
      },
      labelLine: {show: true, length: 10, length2: 8, smooth: .2},
      labelLayout: {moveOverlap: 'shiftY'},
      data: window.CATALOG.energy_distribution
    }]
  });
  const bodyChart = echarts.init(document.querySelector('#body-chart'));
  const data = [...window.CATALOG.body_distribution].reverse();
  bodyChart.setOption({
    grid: {left: 60, right: 20, top: 14, bottom: 28}, tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}},
    xAxis: {type: 'value', splitLine: {lineStyle: {color: '#e1e4df'}}, axisLabel: {color: '#7d8881'}},
    yAxis: {type: 'category', data: data.map((item) => item.name), axisLine: {show: false}, axisTick: {show: false}, axisLabel: {color: '#637068'}},
    series: [{type: 'bar', data: data.map((item) => item.value), barWidth: 12, itemStyle: {color: '#2d7b5d', borderRadius: [0, 6, 6, 0]}}]
  });
  window.addEventListener('resize', () => { energyChart.resize(); bodyChart.resize(); compareChart?.resize(); });
}

renderCatalogCharts();

const analysisUi = {
  loading: document.querySelector('#analysis-loading'),
  error: document.querySelector('#analysis-error'),
  errorMessage: document.querySelector('#analysis-error-message'),
  dashboard: document.querySelector('#analysis-dashboard'),
  period: document.querySelector('#analysis-period'),
  kpis: document.querySelector('#analysis-kpis'),
  filter: document.querySelector('#analysis-group-filter'),
  tableBody: document.querySelector('#analysis-table-body'),
  resultCount: document.querySelector('#analysis-result-count'),
  tableCaption: document.querySelector('#analysis-table-caption')
};
let analysisData = null;
let analysisParameterChart = null;

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function formatDecimal(value, digits = 3) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : '—';
}

function parameterLabel(parameter) {
  return parameter.parameter_name || parameter.feature_name || '未命名参数';
}

function analysisRows(group = '') {
  const rows = Array.isArray(analysisData?.top_parameters) ? analysisData.top_parameters : [];
  return group ? rows.filter((row) => (row.group_name || '其他') === group) : rows;
}

function renderAnalysisKpis(data) {
  const items = [
    ['分析样本', data.analysis_rows, '同期车系销量记录'],
    ['原始参数', data.parameter_definitions, '映射前字段'],
    ['标准特征', data.adapter_features, '编码后特征'],
    ['显著信号', data.significant_features, 'FDR q ≤ 0.05']
  ];
  analysisUi.kpis.innerHTML = items.map(([label, value, note]) => `
    <article class="analysis-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? '—')}</strong><small>${escapeHtml(note)}</small></article>
  `).join('');
}

function signalFor(parameter) {
  const strengthLabels = {strong: '强信号', moderate: '中等信号', weak: '弱信号', not_evaluated: '未评估'};
  const directionLabels = {positive: '正向', negative: '负向', mixed: '方向混合', neutral: '中性', not_evaluated: ''};
  if (parameter.evidence_strength) {
    const strength = strengthLabels[parameter.evidence_strength] || parameter.evidence_strength;
    const direction = directionLabels[parameter.association_direction] || '';
    const className = parameter.association_direction === 'positive' ? 'positive'
      : parameter.association_direction === 'negative' ? 'negative'
      : parameter.association_direction === 'mixed' ? 'mixed' : 'neutral';
    return {label: [strength, direction].filter(Boolean).join(' · '), className};
  }
  const rho = finiteNumber(parameter.spearman_rho);
  const significant = Number(parameter.fdr_q_value) <= .05;
  if (!significant || Math.abs(rho) < .05) return {label: '信号较弱', className: 'neutral'};
  return rho > 0 ? {label: '正向信号', className: 'positive'} : {label: '负向信号', className: 'negative'};
}

function renderParameterCharts(rows) {
  if (!window.echarts) return;
  const alignedRows = [...rows]
    .sort((a, b) => finiteNumber(b.random_forest_importance) - finiteNumber(a.random_forest_importance))
    .slice(0, 12).reverse();
  const labels = alignedRows.map(parameterLabel);
  const correlationValues = alignedRows.map((row) => {
    const value = row.spearman_rho;
    return value === null || value === undefined || value === '' ? null : finiteNumber(value);
  });
  const maximumCorrelation = Math.max(...correlationValues.map((value) => Math.abs(value ?? 0)), .001);
  const correlationExtent = maximumCorrelation * 1.22;
  const zeroCorrelationPoints = correlationValues.flatMap((value, rowIndex) => (
    value === 0 ? [{value: [0, rowIndex], rowIndex}] : []
  ));
  const missingCorrelationPoints = correlationValues.flatMap((value, rowIndex) => (
    value === null ? [{value: [0, rowIndex], rowIndex}] : []
  ));
  const rowArea = {show: true, areaStyle: {color: ['rgba(45,123,93,.035)', 'rgba(255,255,255,0)']}};
  analysisParameterChart?.dispose();
  analysisParameterChart = echarts.init(document.querySelector('#analysis-parameter-chart'));
  analysisParameterChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: ({data, dataIndex}) => {
        const row = alignedRows[data?.rowIndex ?? dataIndex];
        return `<strong>${escapeHtml(parameterLabel(row))}</strong><br>随机森林重要度 ${formatDecimal(row.random_forest_importance, 4)}<br>Spearman 相关系数 ${formatDecimal(row.spearman_rho, 4)}`;
      }
    },
    grid: [
      {left: 165, right: '55%', top: 18, bottom: 34},
      {left: '55%', right: 34, top: 18, bottom: 34}
    ],
    xAxis: [
      {
        type: 'value', gridIndex: 0, min: 0,
        axisLabel: {color: '#7d8881'}, axisLine: {show: false},
        splitLine: {lineStyle: {color: '#e2e5df'}}
      },
      {
        type: 'value', gridIndex: 1, min: -correlationExtent, max: correlationExtent,
        axisLine: {show: true, lineStyle: {color: '#aab4ae'}},
        axisLabel: {color: '#7d8881', formatter: (value) => formatDecimal(value, 2)},
        splitLine: {lineStyle: {color: '#e2e5df'}}
      }
    ],
    yAxis: [
      {
        type: 'category', gridIndex: 0, data: labels,
        axisLine: {show: false}, axisTick: {show: false},
        axisLabel: {color: '#526058', width: 150, overflow: 'truncate'}, splitArea: rowArea
      },
      {
        type: 'category', gridIndex: 1, data: labels,
        axisLine: {show: false}, axisTick: {show: false}, axisLabel: {show: false}, splitArea: rowArea
      }
    ],
    series: [
      {
        name: '随机森林重要度', type: 'bar', xAxisIndex: 0, yAxisIndex: 0, barMaxWidth: 15,
        data: alignedRows.map((row) => finiteNumber(row.random_forest_importance)),
        itemStyle: {color: '#2d7b5d', borderRadius: [0, 6, 6, 0]}
      },
      {
        name: 'Spearman 相关系数', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 15,
        data: correlationValues.map((value) => {
          if (value === null) return null;
          return {
            value,
            label: value === 0 ? {show: false} : {
              show: true,
              formatter: formatDecimal(value, 3),
              position: value > 0 ? 'right' : 'left',
              distance: 5,
              color: '#65716a',
              fontSize: 10,
              fontWeight: 700
            },
            itemStyle: {
              color: value >= 0 ? '#2d7b5d' : '#ff7a3d',
              borderRadius: value >= 0 ? [0, 6, 6, 0] : [6, 0, 0, 6]
            }
          };
        })
      },
      {
        name: '零相关', type: 'scatter', xAxisIndex: 1, yAxisIndex: 1, z: 3,
        symbol: 'circle', symbolSize: 9, data: zeroCorrelationPoints,
        itemStyle: {color: '#8b9690', borderColor: '#fffef8', borderWidth: 2},
        label: {show: true, formatter: '0', position: 'right', distance: 5, color: '#747f79', fontSize: 10, fontWeight: 700}
      },
      {
        name: '不可计算', type: 'scatter', xAxisIndex: 1, yAxisIndex: 1, z: 3,
        symbol: 'diamond', symbolSize: 10, data: missingCorrelationPoints,
        itemStyle: {color: '#fffef8', borderColor: '#9da7a1', borderWidth: 2},
        label: {show: true, formatter: '—', position: 'right', distance: 5, color: '#747f79', fontSize: 11, fontWeight: 700}
      }
    ]
  });
}

function renderParameterTable(rows, group) {
  const sortedRows = [...rows].sort((a, b) => finiteNumber(b.random_forest_importance) - finiteNumber(a.random_forest_importance));
  analysisUi.resultCount.textContent = `${sortedRows.length} 项`;
  analysisUi.tableCaption.textContent = group ? `${group} · 按随机森林重要度排序` : '全部分组 · 按随机森林重要度排序';
  if (!sortedRows.length) {
    analysisUi.tableBody.innerHTML = '<tr><td class="analysis-empty" colspan="6">当前分组暂无可展示参数</td></tr>';
    return;
  }
  analysisUi.tableBody.innerHTML = sortedRows.map((row) => {
    const rho = row.spearman_rho === null || row.spearman_rho === '' ? null : finiteNumber(row.spearman_rho);
    const signal = signalFor(row);
    return `<tr>
      <td>${escapeHtml(parameterLabel(row))}</td>
      <td>${escapeHtml(row.group_name || '其他')} / ${escapeHtml(row.parameter_type || '—')}</td>
      <td class="${rho > 0 ? 'metric-positive' : rho < 0 ? 'metric-negative' : ''}">${rho > 0 ? '+' : ''}${formatDecimal(rho)}</td>
      <td>${formatDecimal(row.fdr_q_value, 4)}</td>
      <td>${formatDecimal(row.random_forest_importance, 4)}</td>
      <td><span class="signal-stack"><span class="signal-badge ${signal.className}">${signal.label}</span><span class="trend-badge" title="${escapeHtml(analysisData?.trend_status_reason || '')}">${row.trend_status === 'insufficient_history' ? '趋势数据不足' : escapeHtml(row.trend_status || '趋势待评估')}</span></span></td>
    </tr>`;
  }).join('');
}

function renderFilteredAnalysis() {
  const group = analysisUi.filter.value;
  const rows = analysisRows(group);
  renderParameterCharts(rows);
  renderParameterTable(rows, group);
}

function renderAnalysis(data) {
  analysisUi.period.textContent = data.sales_period || '未标注';
  renderAnalysisKpis(data);

  const groups = [...new Set(analysisRows().map((row) => row.group_name || '其他'))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
  analysisUi.filter.innerHTML = '<option value="">全部分组</option>' + groups.map((group) => `<option value="${escapeHtml(group)}">${escapeHtml(group)}</option>`).join('');
  renderFilteredAnalysis();
}

async function loadAnalysis() {
  analysisUi.loading.classList.remove('is-hidden');
  analysisUi.error.classList.add('is-hidden');
  analysisUi.dashboard.classList.add('is-hidden');
  try {
    const response = await fetch('/api/analysis/overview?limit=187', {headers: {'Accept': 'application/json'}});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error?.message || '分析接口请求失败');
    if (!body.available) throw new Error((body.warnings || []).join('；') || '尚未生成参数销量分析结果');
    analysisData = body;
    analysisUi.dashboard.classList.remove('is-hidden');
    renderAnalysis(body);
  } catch (error) {
    analysisUi.dashboard.classList.add('is-hidden');
    analysisUi.period.textContent = '不可用';
    analysisUi.errorMessage.textContent = error.message;
    analysisUi.error.classList.remove('is-hidden');
  } finally {
    analysisUi.loading.classList.add('is-hidden');
  }
}

analysisUi.filter?.addEventListener('change', renderFilteredAnalysis);
document.querySelector('#analysis-retry')?.addEventListener('click', loadAnalysis);
window.addEventListener('resize', () => {
  analysisParameterChart?.resize();
});

loadAnalysis();
