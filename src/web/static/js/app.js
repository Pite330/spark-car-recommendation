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

function recommendationCard(car, index) {
  const tags = [car.body_type, car.energy_type, car.seats ? `${car.seats} 座` : null]
    .filter(Boolean).map((tag) => `<span>${escapeHtml(tag)}</span>`).join('');
  return `
    <article class="recommendation-card ${index === 0 ? 'top' : ''}">
      <div class="card-rank"><span>NO. ${String(index + 1).padStart(2, '0')}</span><div class="score-ring" style="--score:${car.score}" data-score="${car.score}"></div></div>
      <span class="card-brand">${escapeHtml(car.brand)}</span>
      <h3>${escapeHtml(car.model_name)}</h3>
      <p class="car-price"><strong>${escapeHtml(displayPrice(car))}</strong> · 参考起售价</p>
      <div class="tags">${tags}</div>
      <p class="reason">${escapeHtml(car.reason)}</p>
      <div class="card-footer">
        <span class="reason-source">${car.reason_source === 'llm' ? (car.reason_provider === 'deepseek' ? 'DeepSeek 说明' : '自然语言说明') : '规则模板说明'}</span>
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
      ? `共找到 ${body.total_candidates} 款候选，按匹配得分稳定排序。`
      : '当前条件下没有候选，请调整预算或核心偏好。';
    relaxedNote.classList.toggle('is-hidden', body.relaxed_conditions.length === 0);
    relaxedNote.textContent = body.relaxed_conditions.length
      ? `为保证候选数量，系统已放宽：${body.relaxed_conditions.join('；')}` : '';
    if (!latestRecommendations.length) {
      recommendationsGrid.innerHTML = '<div class="alert warning">没有返回无关车型。建议扩大预算，或调整车身 / 能源类型后重试。</div>';
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
  ['车身类型', 'body_type', (v) => v],
  ['能源类型', 'energy_type', (v) => v],
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
  const indicators = [
    {key: 'price_min_wan', name: '价格'}, {key: 'range_km', name: '续航'},
    {key: 'horsepower', name: '功率'}, {key: 'seats', name: '座位'}
  ].filter((item) => cars.some((car) => car[item.key] != null));
  const maxima = Object.fromEntries(indicators.map(({key}) => [key, Math.max(...cars.map((car) => Number(car[key]) || 0), 1)]));
  compareChart.setOption({
    color: ['#1b5e44', '#ff7a3d', '#8da642'],
    tooltip: {trigger: 'item'},
    legend: {
      type: 'scroll', orient: 'horizontal', left: 'center', bottom: 10, width: '84%',
      itemWidth: 16, itemHeight: 9, itemGap: 18,
      textStyle: {color: '#637068', fontSize: 11}
    },
    radar: {
      center: ['50%', '43%'], radius: '58%', splitNumber: 4,
      indicator: indicators.map(({key, name}) => ({name, max: maxima[key]})),
      axisName: {color: '#637068', fontSize: 12, padding: [4, 6]},
      axisLine: {lineStyle: {color: '#cfd6d1'}},
      splitLine: {lineStyle: {color: '#d9ddd8'}},
      splitArea: {show: true, areaStyle: {color: ['rgba(27,94,68,.015)', 'rgba(27,94,68,.045)']}}
    },
    series: [{
      type: 'radar', symbolSize: 7, lineStyle: {width: 2},
      data: cars.map((car) => ({
        name: car.model_name,
        value: indicators.map(({key}) => Number(car[key]) || 0),
        areaStyle: {opacity: .10}
      }))
    }]
  });
}

compareButton.addEventListener('click', async () => {
  try {
    const response = await fetch('/api/compare', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({car_ids: [...selectedCars]})});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || '车型对比失败');
    comparisonSection.classList.remove('is-hidden');
    // 先显示容器，再初始化 ECharts。隐藏容器的宽高为 0，会导致雷达图缩在左侧并裁切标签。
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
    series: [{type: 'pie', radius: ['46%', '72%'], center: ['50%', '48%'], itemStyle: {borderColor: '#f4f4ed', borderWidth: 3, borderRadius: 5}, label: {fontSize: 11, color: '#637068'}, data: window.CATALOG.energy_distribution}]
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
