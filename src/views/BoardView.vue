<script setup>
import dayjs from 'dayjs';
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import ChartCard from '@/components/ChartCard.vue';
import DataTable from '@/components/DataTable.vue';
import MetricCard from '@/components/MetricCard.vue';
import { fetchHealth, fetchWeatherData } from '@/api/data.js';

const loading = ref(false);
const healthLoading = ref(false);
const records = ref([]);
const errorMessage = ref('');
const apiStatus = ref('unknown');
const apiSource = ref('--');
const apiMock = ref(false);
const configSnapshot = ref({});
const lastUpdated = ref('--');
const pageSize = ref(20);
const autoRefresh = ref(false);
let autoTimer = null;
let retryTimer = null;
const maxRetryCount = 3;

const timeRange = ref([
  dayjs().subtract(24, 'hour').toDate(),
  dayjs().toDate(),
]);

const latest = computed(() => records.value.at(-1) || {});
const sourceLabel = computed(() => (apiSource.value === 'upstream' ? '上游接口数据' : apiSource.value || '--'));
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

const metrics = computed(() => [
  { label: '温度', value: formatValue(latest.value.wendu), unit: '℃', hint: latest.value.create_time },
  { label: '湿度', value: formatValue(latest.value.shidu), unit: '%RH', hint: '空气相对湿度' },
  { label: '风速', value: formatValue(latest.value.fengsu), unit: 'm/s', hint: `风向 ${formatValue(latest.value.fengxiang)}°` },
  { label: '雨量', value: formatValue(latest.value.yuliang), unit: 'mm', hint: `雨强 ${formatValue(latest.value.yuqiang)}` },
  { label: 'PM2.5', value: formatValue(latest.value.pm25), unit: 'μg/m³', hint: `PM10 ${formatValue(latest.value.pm10)}` },
  { label: '电压', value: formatValue(latest.value.dianya), unit: 'V', hint: `电流 ${formatValue(latest.value.dianliu)} A` },
]);

const chartGroups = [
  {
    name: '气象基础',
    charts: [
      {
        title: '温度与湿度',
        subtitle: '用于判断环境变化趋势和异常波动。',
        series: [
          { key: 'wendu', name: '温度', area: true, unit: '℃' },
          { key: 'shidu', name: '湿度', axis: 'right', unit: '%RH' },
        ],
      },
      {
        title: '风速与风向',
        subtitle: '风向以角度展示，现场可结合设备朝向进一步解释。',
        series: [
          { key: 'fengsu', name: '风速', area: true, unit: 'm/s' },
          { key: 'fengxiang', name: '风向', axis: 'right', unit: '°' },
        ],
      },
      {
        title: '雨量与雨强',
        subtitle: '用于识别降雨过程和短时强降雨。',
        series: [
          { key: 'yuliang', name: '雨量', type: 'bar', unit: 'mm' },
          { key: 'yuqiang', name: '雨强', unit: 'mm/h' },
        ],
      },
      {
        title: '能见度与光强',
        subtitle: '反映现场环境通视条件和光照变化。',
        series: [
          { key: 'nengjiandu', name: '能见度', unit: 'km' },
          { key: 'guangqiang', name: '光强', axis: 'right', area: true, unit: 'lux' },
        ],
      },
    ],
  },
  {
    name: '空气与路况',
    charts: [
      {
        title: 'PM 颗粒物',
        subtitle: 'PM2.5 与 PM10 趋势对比。',
        series: [
          { key: 'pm25', name: 'PM2.5', area: true, unit: 'μg/m³' },
          { key: 'pm10', name: 'PM10', unit: 'μg/m³' },
        ],
      },
      {
        title: '结冰、水膜、积雪',
        subtitle: '0/1 状态类字段，采用阶梯线展示风险状态。',
        yMax: 1.1,
        series: [
          { key: 'jiebin', name: '结冰', step: 'end' },
          { key: 'shuimo', name: '水膜', step: 'end' },
          { key: 'jixue', name: '积雪', step: 'end' },
        ],
      },
    ],
  },
  {
    name: '设备能源',
    charts: [
      {
        title: '电流与电压',
        subtitle: '用于判断采集终端供电稳定性。',
        series: [
          { key: 'dianliu', name: '电流', unit: 'A' },
          { key: 'dianya', name: '电压', axis: 'right', area: true, unit: 'V' },
        ],
      },
      {
        title: '光电、风电、压电',
        subtitle: '用于观察现场多源供能状态。',
        series: [
          { key: 'guangdian', name: '光电', area: true },
          { key: 'fengdian', name: '风电' },
          { key: 'yadian', name: '压电' },
        ],
      },
    ],
  },
];


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
    if (apiStatus.value === 'unknown') apiStatus.value = 'online';
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
  const message = payload?.message || error?.message || '云端数据加载失败';
  const statusPart = error?.status ? `HTTP ${error.status}` : '请求异常';
  return `${statusPart}：${message}`;
}

async function showCloudErrorDialog(message, attempt) {
  const retryText = attempt < maxRetryCount
    ? `系统将在 5 秒后自动第 ${attempt + 1} 次刷新。`
    : '自动刷新次数已达到上限，请检查后端服务、Nginx 转发和上游接口后手动刷新。';
  try {
    await ElMessageBox.alert(
      `${message}\n\n${retryText}`,
      '云端数据加载失败',
      {
        confirmButtonText: '知道了',
        type: 'error',
        customClass: 'dark-message-box',
      },
    );
  } catch (_) {
    // 用户关闭弹窗时不影响自动重试。
  }
}

async function loadData(options = {}) {
  const { attempt = 1, showDialog = true } = options;
  if (!timeRange.value || timeRange.value.length !== 2) {
    ElMessage.warning('请选择完整的开始时间和结束时间');
    return;
  }

  clearRetryTimer();
  loading.value = true;
  errorMessage.value = '';
  try {
    const payload = await fetchWeatherData({
      startTime: timeRange.value[0],
      endTime: timeRange.value[1],
      page: 1,
      pageSize: pageSize.value,
    });
    if (payload?.mock) {
      throw new Error(payload?.message || '后端返回了模拟数据，当前版本已禁用本地数据展示。');
    }
    records.value = Array.isArray(payload?.result?.list) ? payload.result.list : [];
    apiSource.value = payload?.source || 'upstream';
    apiMock.value = false;
    configSnapshot.value = payload?.config || configSnapshot.value || {};
    apiStatus.value = 'online';
    lastUpdated.value = dayjs().format('YYYY-MM-DD HH:mm:ss');
    await resizeCharts();
  } catch (error) {
    records.value = [];
    apiStatus.value = 'offline';
    apiMock.value = false;
    errorMessage.value = makeLoadErrorMessage(error);
    if (showDialog) {
      await showCloudErrorDialog(errorMessage.value, attempt);
    } else {
      ElMessage.error(errorMessage.value);
    }
    if (attempt < maxRetryCount) {
      retryTimer = setTimeout(() => {
        loadData({ attempt: attempt + 1, showDialog: attempt + 1 === maxRetryCount });
      }, 5000);
    }
  } finally {
    loading.value = false;
  }
}

function toggleAutoRefresh(value) {
  autoRefresh.value = value;
  if (autoTimer) {
    clearInterval(autoTimer);
    autoTimer = null;
  }
  if (value) {
    autoTimer = setInterval(loadData, 60 * 1000);
  }
}

onMounted(() => {
  loadData();
  checkHealth(true);
});

onBeforeUnmount(() => {
  if (autoTimer) clearInterval(autoTimer);
  clearRetryTimer();
});
</script>

<template>
  <main class="dashboard-shell">
    <section class="hero-panel">
      <div class="hero-title">
        <p>Atmosphere Monitoring Board</p>
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
      />
      <el-select v-model="pageSize" class="page-size-select" @change="loadData">
        <el-option label="20 条" :value="20" />
        <el-option label="50 条" :value="50" />
        <el-option label="100 条" :value="100" />
        <el-option label="200 条" :value="200" />
        <el-option label="500 条" :value="500" />
      </el-select>
      <el-switch
        :model-value="autoRefresh"
        active-text="60 秒自动刷新"
        inactive-text="手动刷新"
        @change="toggleAutoRefresh"
      />
      <span class="last-updated">最近更新：{{ lastUpdated }}</span>
    </section>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      :type="'error'"
      show-icon
      class="alert-line dark-alert"
      :closable="false"
    />

    <section class="metric-grid" v-loading="loading">
      <MetricCard
        v-for="item in metrics"
        :key="item.label"
        :label="item.label"
        :value="item.value"
        :unit="item.unit"
        :hint="item.hint"
      />
    </section>

    <DataTable :records="records" :loading="loading" />

    <section class="chart-section">
      <div class="panel-title chart-title-line">
        <div>
          <h3>趋势分析</h3>
          <p>所有可视化图表默认展开，便于现场巡检时连续查看气象、路况和供能状态。</p>
        </div>
      </div>

      <div class="chart-group" v-for="group in chartGroups" :key="group.name">
        <div class="chart-group-title">
          <h4>{{ group.name }}</h4>
          <span>{{ group.charts.length }} 个图表</span>
        </div>
        <div class="chart-grid">
          <ChartCard
            v-for="chart in group.charts"
            :key="chart.title"
            :title="chart.title"
            :subtitle="chart.subtitle"
            :records="records"
            :series="chart.series"
            :y-max="chart.yMax"
          />
        </div>
      </div>
    </section>
  </main>
</template>
