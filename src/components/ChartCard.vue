<script setup>
import * as echarts from 'echarts';
import dayjs from 'dayjs';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = defineProps({
  title: { type: String, required: true },
  records: { type: Array, default: () => [] },
  rawCount: { type: Number, default: 0 },
  series: { type: Array, required: true },
  type: { type: String, default: 'line' },
  yMax: { type: Number, default: null },
  timeRange: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  renderDelay: { type: Number, default: 0 },
});

const chartRef = ref(null);
const rendering = ref(false);
let chart = null;
let resizeObserver = null;
let retryTimer = null;
let renderTimer = null;
let rafId = null;

function chartWidth() {
  return chartRef.value?.clientWidth || window.innerWidth || 1024;
}

function isMobileChart() {
  return chartWidth() <= 560;
}

function isVeryNarrowChart() {
  return chartWidth() <= 420;
}

function toTimestamp(value) {
  if (value === undefined || value === null || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (value instanceof Date) return value.getTime();
  const text = String(value).trim();
  if (/^\d{13}$/.test(text)) return Number(text);
  if (/^\d{10}$/.test(text)) return Number(text) * 1000;
  const parsed = dayjs(text);
  return parsed.isValid() ? parsed.valueOf() : null;
}

function toNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatNumber(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  if (Math.abs(num) >= 1000) return num.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (Math.abs(num) >= 100) return num.toFixed(0);
  if (Math.abs(num) >= 10) return num.toFixed(1).replace(/\.0$/, '');
  return num.toFixed(2).replace(/\.00$/, '').replace(/0$/, '');
}

const rangeBounds = computed(() => {
  if (!Array.isArray(props.timeRange) || props.timeRange.length !== 2) return { start: null, end: null };
  const start = toTimestamp(props.timeRange[0]);
  const end = toTimestamp(props.timeRange[1]);
  if (start === null || end === null) return { start: null, end: null };
  return start <= end ? { start, end } : { start: end, end: start };
});

const chartRecords = computed(() => (Array.isArray(props.records) ? props.records : []));
const hasData = computed(() => chartRecords.value.length > 0);

function getDataSpanMs() {
  const { start, end } = rangeBounds.value;
  if (start !== null && end !== null && end > start) return end - start;
  const times = chartRecords.value.map((record) => toTimestamp(record.timestamp || record.create_time)).filter((value) => value !== null);
  if (times.length < 2) return 0;
  return Math.max(...times) - Math.min(...times);
}

function formatXAxisLabel(value) {
  const span = getDataSpanMs();
  if (span >= 60 * 24 * 60 * 60 * 1000) return dayjs(value).format('YYYY-MM');
  if (span >= 3 * 24 * 60 * 60 * 1000) return dayjs(value).format('MM-DD');
  if (span >= 24 * 60 * 60 * 1000) return dayjs(value).format('MM-DD HH:mm');
  return dayjs(value).format('HH:mm');
}

function buildSeries(item) {
  const chartType = item.type || props.type;
  return {
    name: item.name,
    type: chartType,
    yAxisIndex: item.axis === 'right' ? 1 : 0,
    smooth: chartType === 'line' ? item.smooth ?? !isMobileChart() : false,
    step: item.step,
    showSymbol: false,
    symbolSize: isMobileChart() ? 4 : 5,
    lineStyle: { width: isMobileChart() ? 2 : 2.2 },
    barMaxWidth: isMobileChart() ? 10 : 14,
    areaStyle: item.area ? { opacity: isMobileChart() ? 0.1 : 0.13 } : undefined,
    emphasis: { focus: 'series' },
    progressive: 200,
    progressiveThreshold: 600,
    data: chartRecords.value
      .map((record, index) => {
        const timestamp = toTimestamp(record.timestamp || record.create_time) ?? index;
        const value = toNumber(record[item.key]);
        return value === null ? null : [timestamp, value];
      })
      .filter(Boolean),
  };
}

function buildYAxis() {
  const mobile = isMobileChart();
  const veryNarrow = isVeryNarrowChart();
  const hasRightAxis = props.series.some((item) => item.axis === 'right');
  const baseAxis = {
    type: 'value',
    min: 0,
    max: props.yMax || undefined,
    splitNumber: mobile ? 4 : 5,
    axisLabel: {
      color: '#a9bbd8',
      fontSize: mobile ? 10 : 12,
      margin: mobile ? 4 : 8,
      formatter: formatNumber,
    },
    axisLine: { lineStyle: { color: '#294569' } },
    axisTick: { show: !mobile, lineStyle: { color: '#294569' } },
    splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.14)' } },
  };
  if (!hasRightAxis) return baseAxis;
  return [
    baseAxis,
    {
      type: 'value',
      min: 0,
      splitNumber: mobile ? 4 : 5,
      axisLabel: {
        color: '#a9bbd8',
        fontSize: mobile ? 10 : 12,
        margin: veryNarrow ? 2 : 4,
        formatter: formatNumber,
      },
      axisLine: { lineStyle: { color: '#294569' } },
      axisTick: { show: !mobile, lineStyle: { color: '#294569' } },
      splitLine: { show: false },
    },
  ];
}

function buildOption() {
  const mobile = isMobileChart();
  const veryNarrow = isVeryNarrowChart();
  const hasRightAxis = props.series.some((item) => item.axis === 'right');
  const span = getDataSpanMs();
  const dayMs = 24 * 60 * 60 * 1000;
  const { start, end } = rangeBounds.value;
  return {
    backgroundColor: 'transparent',
    animation: false,
    color: ['#60a5fa', '#a3e635', '#f59e0b', '#22d3ee', '#f472b6'],
    tooltip: {
      trigger: 'axis',
      confine: true,
      appendToBody: true,
      backgroundColor: 'rgba(7, 17, 31, 0.96)',
      borderColor: 'rgba(148, 163, 184, 0.28)',
      textStyle: { color: '#e5edf9', fontSize: mobile ? 11 : 12 },
      valueFormatter: (value) => formatNumber(value),
    },
    legend: {
      top: mobile ? 2 : 0,
      right: mobile ? 'center' : 4,
      orient: 'horizontal',
      itemWidth: mobile ? 14 : 18,
      itemHeight: mobile ? 7 : 8,
      itemGap: mobile ? 10 : 16,
      textStyle: { color: '#dbeafe', fontSize: mobile ? 11 : 12 },
    },
    grid: mobile
      ? { left: veryNarrow ? 2 : 4, right: hasRightAxis ? (veryNarrow ? 2 : 4) : 2, top: 42, bottom: 28, containLabel: true }
      : { left: 12, right: hasRightAxis ? 14 : 8, top: 48, bottom: 36, containLabel: true },
    xAxis: {
      type: 'time',
      boundaryGap: false,
      min: start ?? undefined,
      max: end ?? undefined,
      minInterval: span >= 3 * dayMs ? dayMs : 5 * 60 * 1000,
      maxInterval: span >= 3 * dayMs ? 3 * dayMs : 60 * 60 * 1000,
      axisLabel: {
        color: '#a9bbd8',
        fontSize: mobile ? 10 : 12,
        hideOverlap: true,
        margin: mobile ? 7 : 10,
        formatter(value) {
          return formatXAxisLabel(value);
        },
      },
      axisLine: { lineStyle: { color: '#294569' } },
      axisTick: { show: !mobile, lineStyle: { color: '#294569' } },
      splitLine: { show: false },
    },
    yAxis: buildYAxis(),
    series: props.series.map(buildSeries),
  };
}

function cancelScheduledRender() {
  clearTimeout(retryTimer);
  clearTimeout(renderTimer);
  if (rafId) cancelAnimationFrame(rafId);
  retryTimer = null;
  renderTimer = null;
  rafId = null;
}

function renderChart() {
  if (props.loading) return;
  if (!chartRef.value || !hasData.value) {
    rendering.value = false;
    return;
  }
  const width = chartRef.value.clientWidth;
  const height = chartRef.value.clientHeight;
  if (width < 80 || height < 80) {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(renderChart, 120);
    return;
  }
  if (!chart) chart = echarts.init(chartRef.value, null, { renderer: 'canvas' });
  chart.setOption(buildOption(), true, true);
  chart.resize();
  rendering.value = false;
}

function scheduleRender() {
  cancelScheduledRender();
  if (props.loading) return;
  if (!hasData.value) {
    chart?.clear();
    rendering.value = false;
    return;
  }
  rendering.value = true;
  renderTimer = setTimeout(() => {
    rafId = requestAnimationFrame(renderChart);
  }, Math.max(0, props.renderDelay));
}

function resizeChart() {
  if (!chart || props.loading) return;
  chart.resize();
  chart.setOption(buildOption(), true, true);
}

watch(
  () => [props.records, props.series, props.yMax, props.timeRange, props.loading],
  async () => {
    await nextTick();
    scheduleRender();
  },
  { deep: false },
);

onMounted(async () => {
  await nextTick();
  scheduleRender();
  if (chartRef.value) {
    resizeObserver = new ResizeObserver(resizeChart);
    resizeObserver.observe(chartRef.value);
  }
  window.addEventListener('resize', resizeChart);
  window.addEventListener('orientationchange', resizeChart);
});

onBeforeUnmount(() => {
  cancelScheduledRender();
  window.removeEventListener('resize', resizeChart);
  window.removeEventListener('orientationchange', resizeChart);
  resizeObserver?.disconnect();
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <section class="chart-card" v-loading="loading || rendering">
    <div class="chart-header">
      <div>
        <h3>{{ title }}</h3>
      </div>
      <span class="chart-count">{{ chartRecords.length }} 小时 / {{ rawCount }} 条</span>
    </div>
    <div v-if="hasData" ref="chartRef" class="chart-canvas"></div>
    <div v-else-if="loading" class="chart-skeleton">
      <span>图表数据准备中</span>
    </div>
    <el-empty v-else description="当前筛选时间区间内暂无数据" :image-size="80" />
  </section>
</template>
