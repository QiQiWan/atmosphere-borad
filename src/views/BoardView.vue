<script setup>
import dayjs from 'dayjs';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import ChartCard from '@/components/ChartCard.vue';
import DataTable from '@/components/DataTable.vue';
import MetricCard from '@/components/MetricCard.vue';
import { fetchHealth, fetchWeatherData, formatTimeRangeText, getDefaultTimeRange } from '@/api/data.js';

const loading = ref(false);
const chartLoading = ref(false);
const healthLoading = ref(false);
const records = shallowRef([]);
const errorMessage = ref('');
const apiStatus = ref('unknown');
const apiSource = ref('--');
const configSnapshot = ref({});
const lastUpdated = ref('--');
const pageSize = ref(5000);
const autoRefresh = ref(false);
const loadingStage = ref('待加载');
const loadingPercent = ref(0);
let autoTimer = null;
let retryTimer = null;
let activeLoadToken = 0;
const maxRetryCount = 3;

const timeRange = ref(getDefaultTimeRange());

const sourceLabel = computed(() => {
  if (apiSource.value === 'upstream') return '云端数据';
  if (apiSource.value === 'database-cache') return '服务器数据';
  if (apiSource.value === 'database-partial-cache') return '服务器数据';
  if (apiSource.value === 'prefetching') return '数据准备中';
  return apiSource.value || '--';
});
const envLabel = computed(() => (configSnapshot.value?.has_secret_key ? '密钥已加载' : '密钥未加载'));
const statusType = computed(() => {
  if (apiStatus.value === 'online') return 'success';
  if (apiStatus.value === 'offline') return 'danger';
  return 'info';
});
const statusText = computed(() => {
  if (apiStatus.value === 'online') return '接口正常';
  if (apiStatus.value === 'offline') return '接口异常';
  return '未检测';
});
const selectedTimeText = computed(() => formatTimeRangeText(timeRange.value));
const isBusy = computed(() => loading.value || chartLoading.value);

function yieldToBrowser() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function setLoadStage(text, percent) {
  loadingStage.value = text;
  loadingPercent.value = percent;
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

const selectedBounds = computed(() => {
  if (!Array.isArray(timeRange.value) || timeRange.value.length !== 2) return { start: null, end: null };
  const start = toTimestamp(timeRange.value[0]);
  const end = toTimestamp(timeRange.value[1]);
  if (start === null || end === null) return { start: null, end: null };
  return start <= end ? { start, end } : { start: end, end: start };
});

const visibleRecords = computed(() => {
  const rows = Array.isArray(records.value) ? records.value : [];
  const { start, end } = selectedBounds.value;
  if (start === null || end === null) return rows;
  return rows.filter((record) => {
    const ts = toTimestamp(record.create_time || record.receive_time || record.time || record.timestamp);
    return ts !== null && ts >= start && ts <= end;
  });
});

const latest = computed(() => {
  let latestRecord = null;
  let latestTs = -Infinity;
  visibleRecords.value.forEach((record) => {
    const ts = toTimestamp(record.create_time || record.receive_time || record.time || record.timestamp);
    if (ts !== null && ts >= latestTs) {
      latestRecord = record;
      latestTs = ts;
    }
  });
  return latestRecord || {};
});

const metrics = computed(() => [
  { label: '温度', value: formatValue(latest.value.wendu), unit: '℃', hint: latest.value.create_time || latest.value.receive_time || '' },
  { label: '湿度', value: formatValue(latest.value.shidu), unit: '%RH', hint: '' },
  { label: '风速', value: formatValue(latest.value.fengsu), unit: 'm/s', hint: `风向 ${formatValue(latest.value.fengxiang)}°` },
  { label: '雨量', value: formatValue(latest.value.yuliang), unit: 'mm', hint: `雨强 ${formatValue(latest.value.yuqiang)}` },
  { label: 'PM2.5', value: formatValue(latest.value.pm25), unit: 'μg/m³', hint: `PM10 ${formatValue(latest.value.pm10)}` },
  { label: '电压', value: formatValue(latest.value.dianya), unit: 'V', hint: `电流 ${formatValue(latest.value.dianliu)} A` },
]);

const chartGroups = [
  {
    name: '气象基础',
    charts: [
      { title: '温度与湿度', series: [{ key: 'wendu', name: '温度', area: true, unit: '℃' }, { key: 'shidu', name: '湿度', axis: 'right', unit: '%RH' }] },
      { title: '风速与风向', series: [{ key: 'fengsu', name: '风速', area: true, unit: 'm/s' }, { key: 'fengxiang', name: '风向', axis: 'right', unit: '°' }] },
      { title: '雨量与雨强', series: [{ key: 'yuliang', name: '雨量', type: 'bar', unit: 'mm' }, { key: 'yuqiang', name: '雨强', unit: 'mm/h' }] },
      { title: '能见度与光强', series: [{ key: 'nengjiandu', name: '能见度', unit: 'km' }, { key: 'guangqiang', name: '光强', axis: 'right', area: true, unit: 'lux' }] },
    ],
  },
  {
    name: '空气与路况',
    charts: [
      { title: 'PM 颗粒物', series: [{ key: 'pm25', name: 'PM2.5', area: true, unit: 'μg/m³' }, { key: 'pm10', name: 'PM10', unit: 'μg/m³' }] },
      { title: '结冰、水膜、积雪', yMax: 1.1, series: [{ key: 'jiebin', name: '结冰', step: 'end' }, { key: 'shuimo', name: '水膜', step: 'end' }, { key: 'jixue', name: '积雪', step: 'end' }] },
    ],
  },
  {
    name: '设备能源',
    charts: [
      { title: '电流与电压', series: [{ key: 'dianliu', name: '电流', unit: 'A' }, { key: 'dianya', name: '电压', axis: 'right', area: true, unit: 'V' }] },
      { title: '光电、风电、压电', series: [{ key: 'guangdian', name: '光电', area: true }, { key: 'fengdian', name: '风电' }, { key: 'yadian', name: '压电' }] },
    ],
  },
];

const chartKeyList = Array.from(new Set(chartGroups.flatMap((group) => group.charts.flatMap((chart) => chart.series.map((item) => item.key)))));

function floorToHour(timestamp) {
  return Math.floor(timestamp / (60 * 60 * 1000)) * 60 * 60 * 1000;
}

const hourlyRecords = computed(() => {
  const buckets = new Map();
  const { start, end } = selectedBounds.value;
  visibleRecords.value.forEach((record) => {
    const timestamp = toTimestamp(record.create_time || record.receive_time || record.time || record.timestamp);
    if (timestamp === null) return;
    if (start !== null && timestamp < start) return;
    if (end !== null && timestamp > end) return;
    const hour = floorToHour(timestamp);
    if (!buckets.has(hour)) {
      buckets.set(hour, {
        timestamp: hour,
        create_time: dayjs(hour).format('YYYY-MM-DD HH:00:00'),
        sample_count: 0,
        __sum: {},
        __countByKey: {},
      });
    }
    const bucket = buckets.get(hour);
    bucket.sample_count += 1;
    chartKeyList.forEach((key) => {
      const value = toNumber(record[key]);
      if (value === null) return;
      bucket.__sum[key] = (bucket.__sum[key] || 0) + value;
      bucket.__countByKey[key] = (bucket.__countByKey[key] || 0) + 1;
    });
  });
  return Array.from(buckets.values()).sort((a, b) => a.timestamp - b.timestamp).map((bucket) => {
    const row = {
      timestamp: bucket.timestamp,
      create_time: bucket.create_time,
      sample_count: bucket.sample_count,
    };
    chartKeyList.forEach((key) => {
      const count = bucket.__countByKey[key] || 0;
      row[key] = count > 0 ? Number((bucket.__sum[key] / count).toFixed(4)) : null;
    });
    return row;
  });
});

function chartIndex(groupIndex, chartIndexInGroup) {
  let count = 0;
  for (let i = 0; i < groupIndex; i += 1) count += chartGroups[i].charts.length;
  return count + chartIndexInGroup;
}

function formatValue(value) {
  if (value === undefined || value === null || value === '') return '--';
  const num = Number(value);
  return Number.isFinite(num) ? Number(num.toFixed(2)) : value;
}

async function resizeCharts() {
  await nextTick();
  window.dispatchEvent(new Event('resize'));
}

async function checkHealth(silent = false) {
  healthLoading.value = true;
  try {
    const payload = await fetchHealth();
    configSnapshot.value = payload?.config || {};
    apiStatus.value = 'online';
    if (!silent) ElMessage.success('后端健康检查正常');
  } catch (error) {
    apiStatus.value = 'offline';
    if (!silent) ElMessage.error(`后端健康检查失败：${error.message}`);
  } finally {
    healthLoading.value = false;
  }
}

function clearRetryTimer() {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
}

function makeLoadErrorMessage(error) {
  const payload = error?.payload;
  const message = payload?.message || error?.message || '数据加载失败';
  const statusPart = error?.status ? `HTTP ${error.status}` : '请求异常';
  return `${statusPart}：${message}`;
}

async function showCloudErrorDialog(message, attempt) {
  const retryText = attempt < maxRetryCount
    ? `系统将在 5 秒后自动第 ${attempt + 1} 次刷新。`
    : '自动刷新次数已达到上限，请检查后端服务、Nginx 转发和上游接口后手动刷新。';
  try {
    await ElMessageBox.alert(`${message}\n\n${retryText}`, '数据加载失败', {
      confirmButtonText: '知道了',
      type: 'error',
      customClass: 'dark-message-box',
    });
  } catch (_) {
    // ignore close
  }
}

async function applyPayload(payload, token) {
  if (payload?.mock) throw new Error(payload?.message || '后端返回了模拟数据。');
  setLoadStage('处理监测记录', 55);
  await yieldToBrowser();
  if (token !== activeLoadToken) return;
  const list = Array.isArray(payload?.result?.list) ? payload.result.list : [];
  records.value = list;
  apiSource.value = payload?.source || 'database-cache';
  configSnapshot.value = payload?.config || configSnapshot.value || {};
  apiStatus.value = 'online';
  lastUpdated.value = dayjs().format('YYYY-MM-DD HH:mm:ss');
  setLoadStage('生成小时聚合数据', 70);
  await yieldToBrowser();
  setLoadStage('分批渲染图表', 85);
  chartLoading.value = false;
  await nextTick();
  await resizeCharts();
}

async function loadData(options = {}) {
  const { attempt = 1, showDialog = true } = options;
  if (!timeRange.value || timeRange.value.length !== 2) {
    ElMessage.warning('请选择完整的开始时间和结束时间');
    return;
  }
  clearRetryTimer();
  const token = ++activeLoadToken;
  loading.value = true;
  chartLoading.value = true;
  errorMessage.value = '';
  setLoadStage('请求服务器数据库', 15);
  try {
    await yieldToBrowser();
    const payload = await fetchWeatherData({ startTime: timeRange.value[0], endTime: timeRange.value[1], page: 1, pageSize: pageSize.value });
    if (token !== activeLoadToken) return;
    setLoadStage('接收数据完成', 45);
    await applyPayload(payload, token);
    if (token !== activeLoadToken) return;
    setLoadStage('加载完成', 100);
    setTimeout(() => {
      if (token === activeLoadToken) loading.value = false;
    }, 180);
  } catch (error) {
    if (token !== activeLoadToken) return;
    records.value = [];
    chartLoading.value = false;
    apiStatus.value = 'offline';
    errorMessage.value = makeLoadErrorMessage(error);
    setLoadStage('加载失败', 100);
    loading.value = false;
    if (showDialog) await showCloudErrorDialog(errorMessage.value, attempt);
    if (attempt < maxRetryCount) {
      retryTimer = setTimeout(() => loadData({ attempt: attempt + 1, showDialog: attempt + 1 === maxRetryCount }), 5000);
    }
  }
}

function toggleAutoRefresh(value) {
  autoRefresh.value = value;
  if (autoTimer) {
    clearInterval(autoTimer);
    autoTimer = null;
  }
  if (value) autoTimer = setInterval(() => loadData({ showDialog: false }), 60 * 1000);
}

onMounted(() => {
  loadData();
  checkHealth(true);
});

onBeforeUnmount(() => {
  activeLoadToken += 1;
  if (autoTimer) clearInterval(autoTimer);
  clearRetryTimer();
});
</script>

<template>
  <main class="dashboard-shell dashboard-shell-plain">
    <section class="hero-panel compact-hero">
      <div class="hero-title">
        <h1>荆襄气象监测看板</h1>
      </div>
      <div class="hero-actions">
        <el-tag :type="statusType" effect="dark" size="large">{{ statusText }}</el-tag>
        <el-tag effect="plain" size="large">{{ sourceLabel }}</el-tag>
        <el-tag :type="configSnapshot?.has_secret_key ? 'success' : 'warning'" effect="plain" size="large">{{ envLabel }}</el-tag>
        <el-button :loading="healthLoading" @click="checkHealth(false)">健康检查</el-button>
        <el-button type="primary" :loading="loading" @click="loadData">刷新数据</el-button>
      </div>
    </section>

    <section class="filter-panel">
      <el-date-picker
        v-model="timeRange"
        type="datetimerange"
        range-separator="至"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        value-format="YYYY-MM-DD HH:mm:ss"
        format="YYYY-MM-DD HH:mm:ss"
        class="date-picker"
        @change="loadData"
      />
      <el-select v-model="pageSize" class="page-size-select" @change="loadData">
        <el-option label="500 条" :value="500" />
        <el-option label="1000 条" :value="1000" />
        <el-option label="2000 条" :value="2000" />
        <el-option label="5000 条" :value="5000" />
      </el-select>
      <el-switch :model-value="autoRefresh" active-text="60 秒自动刷新" inactive-text="手动刷新" @change="toggleAutoRefresh" />
      <span class="last-updated">最近更新：{{ lastUpdated }}</span>
      <span class="range-summary">{{ selectedTimeText }}</span>
    </section>

    <section v-if="isBusy" class="load-progress-panel">
      <div class="load-progress-text">
        <span>{{ loadingStage }}</span>
        <span>{{ visibleRecords.length }} 条原始记录 / {{ hourlyRecords.length }} 小时聚合</span>
      </div>
      <el-progress :percentage="loadingPercent" :stroke-width="8" :show-text="false" />
    </section>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon class="alert-line dark-alert" :closable="false" />

    <section class="metric-grid" v-loading="loading">
      <MetricCard v-for="item in metrics" :key="item.label" :label="item.label" :value="item.value" :unit="item.unit" :hint="item.hint" />
    </section>

    <DataTable :records="visibleRecords" :loading="loading" />

    <section class="chart-section">
      <div class="chart-group" v-for="(group, groupIdx) in chartGroups" :key="group.name">
        <div class="chart-group-title">
          <h4>{{ group.name }}</h4>
          <span>{{ group.charts.length }} 个图表</span>
        </div>
        <div class="chart-grid">
          <ChartCard
            v-for="(chart, chartIdx) in group.charts"
            :key="chart.title"
            :title="chart.title"
            :records="hourlyRecords"
            :raw-count="visibleRecords.length"
            :series="chart.series"
            :y-max="chart.yMax"
            :time-range="timeRange"
            :loading="chartLoading || loading"
            :render-delay="chartIndex(groupIdx, chartIdx) * 90"
          />
        </div>
      </div>
    </section>
  </main>
</template>
