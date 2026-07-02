<script setup>
import * as echarts from 'echarts';
import dayjs from 'dayjs';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  records: { type: Array, default: () => [] },
  series: { type: Array, required: true },
  type: { type: String, default: 'line' },
  yMax: { type: Number, default: null },
});

const chartRef = ref(null);
let chart = null;
let resizeObserver = null;
let retryTimer = null;

const hasData = computed(() => Array.isArray(props.records) && props.records.length > 0);

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
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.valueOf() : null;
}

function toNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : 0;
}

function formatNumber(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  if (Math.abs(num) >= 1000) return num.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (Math.abs(num) >= 100) return num.toFixed(0);
  if (Math.abs(num) >= 10) return num.toFixed(1).replace(/\.0$/, '');
  return num.toFixed(2).replace(/\.00$/, '').replace(/0$/, '');
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
    lineStyle: { width: isMobileChart() ? 2 : 2.4 },
    barMaxWidth: isMobileChart() ? 10 : 14,
    areaStyle: item.area ? { opacity: isMobileChart() ? 0.1 : 0.13 } : undefined,
    emphasis: { focus: 'series' },
    data: props.records
      .map((record, index) => {
        const timestamp = toTimestamp(record.create_time || record.time) ?? index;
        return [timestamp, toNumber(record[item.key])];
      })
      .filter((pair) => pair[0] !== null),
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
  return {
    backgroundColor: 'transparent',
    animationDuration: 350,
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
      ? {
          left: veryNarrow ? 2 : 4,
          right: hasRightAxis ? (veryNarrow ? 2 : 4) : 2,
          top: 42,
          bottom: 28,
          containLabel: true,
        }
      : {
          left: 12,
          right: hasRightAxis ? 14 : 8,
          top: 48,
          bottom: 36,
          containLabel: true,
        },
    xAxis: {
      type: 'time',
      boundaryGap: false,
      minInterval: 5 * 60 * 1000,
      maxInterval: 60 * 60 * 1000,
      axisLabel: {
        color: '#a9bbd8',
        fontSize: mobile ? 10 : 12,
        hideOverlap: true,
        margin: mobile ? 7 : 10,
        formatter(value) {
          return dayjs(value).format(mobile ? 'HH:mm' : 'HH:mm');
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

function renderChart() {
  if (!chartRef.value || !hasData.value) return;
  const width = chartRef.value.clientWidth;
  const height = chartRef.value.clientHeight;
  if (width < 80 || height < 80) {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(renderChart, 120);
    return;
  }
  if (!chart) chart = echarts.init(chartRef.value, null, { renderer: 'canvas' });
  chart.setOption(buildOption(), true);
  chart.resize();
}

function resizeChart() {
  if (!chart) return;
  chart.resize();
  chart.setOption(buildOption(), true);
}

watch(
  () => [props.records, props.series, props.yMax],
  async () => {
    await nextTick();
    renderChart();
  },
  { deep: true },
);

onMounted(async () => {
  await nextTick();
  renderChart();
  if (chartRef.value) {
    resizeObserver = new ResizeObserver(resizeChart);
    resizeObserver.observe(chartRef.value);
  }
  window.addEventListener('resize', resizeChart);
  window.addEventListener('orientationchange', resizeChart);
});

onBeforeUnmount(() => {
  clearTimeout(retryTimer);
  window.removeEventListener('resize', resizeChart);
  window.removeEventListener('orientationchange', resizeChart);
  resizeObserver?.disconnect();
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <section class="chart-card">
    <div class="chart-header">
      <div>
        <h3>{{ title }}</h3>
        <p>{{ subtitle }}</p>
      </div>
      <span class="chart-count">{{ records.length }} 条</span>
    </div>
    <div v-if="hasData" ref="chartRef" class="chart-canvas"></div>
    <el-empty v-else description="暂无数据" :image-size="80" />
  </section>
</template>
