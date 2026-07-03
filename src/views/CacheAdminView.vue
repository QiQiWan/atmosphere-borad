<script setup>
import dayjs from 'dayjs';
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  deleteCacheDay,
  deleteCacheRecord,
  fetchCacheDayDetail,
  fetchCacheProgress,
  fetchCacheScan,
  refreshCacheDay,
  formatTimeRangeText,
} from '@/api/data.js';

const scanLoading = ref(false);
const actionLoading = ref(false);
const detailLoading = ref(false);
const scan = ref(null);
const progress = ref(null);
const selectedDate = ref('');
const dayDetail = ref(null);
const drawerVisible = ref(false);
const hourFilter = ref('all');
const recordPage = ref(1);
const recordPageSize = ref(100);

const range = ref([
  dayjs().subtract(29, 'day').startOf('day').format('YYYY-MM-DD HH:mm:ss'),
  dayjs().endOf('day').format('YYYY-MM-DD HH:mm:ss'),
]);

const rangeText = computed(() => formatTimeRangeText(range.value));
const days = computed(() => scan.value?.days || []);
const summary = computed(() => ({
  dayCount: scan.value?.day_count || 0,
  coveredDays: scan.value?.covered_days || 0,
  daysWithRecords: scan.value?.days_with_records || 0,
  zeroDays: scan.value?.covered_zero_record_days || 0,
  missingDays: scan.value?.missing_coverage_days || 0,
  totalRecords: scan.value?.total_records || 0,
}));

const detailRecords = computed(() => dayDetail.value?.records || []);
const detailHours = computed(() => dayDetail.value?.hours || []);
const detailPagination = computed(() => dayDetail.value?.pagination || { page: 1, page_size: 100, total: 0 });

function statusText(status) {
  if (status === 'covered_with_records') return '有数据';
  if (status === 'covered_no_records') return '已覆盖无数据';
  if (status === 'not_covered') return '未覆盖';
  return status || '--';
}

function statusType(status) {
  if (status === 'covered_with_records') return 'success';
  if (status === 'covered_no_records') return 'warning';
  if (status === 'not_covered') return 'danger';
  return 'info';
}

function activeHourText(row) {
  const hours = row?.active_hours || [];
  if (!hours.length) return '--';
  return hours.map((item) => String(item).padStart(2, '0')).join(', ');
}

function formatNumber(value) {
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toLocaleString('zh-CN') : value;
}

async function loadScan() {
  scanLoading.value = true;
  try {
    const payload = await fetchCacheScan({ startTime: range.value?.[0], endTime: range.value?.[1] });
    scan.value = payload?.scan || null;
    if (scan.value?.error) ElMessage.error(scan.value.error);
  } catch (error) {
    ElMessage.error(`缓存扫描失败：${error.message}`);
  } finally {
    scanLoading.value = false;
  }
}

async function loadProgress() {
  try {
    const payload = await fetchCacheProgress();
    progress.value = payload?.prefetch || null;
  } catch (_) {
    progress.value = null;
  }
}

async function openDay(row) {
  selectedDate.value = row.date;
  hourFilter.value = 'all';
  recordPage.value = 1;
  drawerVisible.value = true;
  await loadDayDetail();
}

async function loadDayDetail() {
  if (!selectedDate.value) return;
  detailLoading.value = true;
  try {
    const payload = await fetchCacheDayDetail(selectedDate.value, {
      hour: hourFilter.value === 'all' ? null : hourFilter.value,
      page: recordPage.value,
      pageSize: recordPageSize.value,
    });
    dayDetail.value = payload?.detail || null;
    if (dayDetail.value?.error) ElMessage.error(dayDetail.value.error);
  } catch (error) {
    ElMessage.error(`日期详情加载失败：${error.message}`);
  } finally {
    detailLoading.value = false;
  }
}

async function refreshDay(row) {
  try {
    await ElMessageBox.confirm(`确认重新拉取 ${row.date} 的远程数据？`, '重新拉取日期缓存', {
      confirmButtonText: '重新拉取',
      cancelButtonText: '取消',
      type: 'warning',
      customClass: 'dark-message-box',
    });
  } catch (_) {
    return;
  }
  actionLoading.value = true;
  try {
    await refreshCacheDay(row.date);
    ElMessage.success('已提交重新拉取任务，请稍后刷新扫描结果');
    await loadProgress();
  } catch (error) {
    ElMessage.error(`重新拉取失败：${error.message}`);
  } finally {
    actionLoading.value = false;
  }
}

async function removeDay(row) {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.date} 的服务器缓存？该操作不会删除第三方接口数据。`, '删除日期缓存', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'error',
      customClass: 'dark-message-box',
    });
  } catch (_) {
    return;
  }
  actionLoading.value = true;
  try {
    await deleteCacheDay(row.date);
    ElMessage.success('日期缓存已删除');
    await loadScan();
    if (selectedDate.value === row.date) await loadDayDetail();
  } catch (error) {
    ElMessage.error(`删除失败：${error.message}`);
  } finally {
    actionLoading.value = false;
  }
}

async function removeRecord(row) {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.create_time || row.record_key} 这条缓存记录？`, '删除记录缓存', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'error',
      customClass: 'dark-message-box',
    });
  } catch (_) {
    return;
  }
  detailLoading.value = true;
  try {
    await deleteCacheRecord(row.record_key);
    ElMessage.success('记录缓存已删除');
    await loadDayDetail();
    await loadScan();
  } catch (error) {
    ElMessage.error(`删除记录失败：${error.message}`);
  } finally {
    detailLoading.value = false;
  }
}

function onDetailPageChange(page) {
  recordPage.value = page;
  loadDayDetail();
}

function onDetailSizeChange(size) {
  recordPageSize.value = size;
  recordPage.value = 1;
  loadDayDetail();
}

onMounted(() => {
  loadScan();
  loadProgress();
});
</script>

<template>
  <main class="dashboard-shell cache-admin-shell">
    <section class="hero-panel compact-hero cache-admin-hero">
      <div class="hero-title">
        <h1>服务器缓存管理</h1>
      </div>
      <div class="hero-actions">
        <el-button :loading="scanLoading" @click="loadScan">扫描缓存</el-button>
        <el-button :loading="actionLoading" @click="loadProgress">任务状态</el-button>
      </div>
    </section>

    <section class="filter-panel cache-admin-filter">
      <el-date-picker
        v-model="range"
        type="datetimerange"
        range-separator="至"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        value-format="YYYY-MM-DD HH:mm:ss"
        format="YYYY-MM-DD HH:mm:ss"
        class="date-picker"
      />
      <el-button type="primary" :loading="scanLoading" @click="loadScan">查询区间</el-button>
      <span class="range-summary">{{ rangeText }}</span>
    </section>

    <section class="cache-admin-summary">
      <div class="cache-stat-card"><span>覆盖日期</span><strong>{{ summary.coveredDays }}/{{ summary.dayCount }}</strong></div>
      <div class="cache-stat-card"><span>有数据日期</span><strong>{{ summary.daysWithRecords }}</strong></div>
      <div class="cache-stat-card"><span>已覆盖无数据</span><strong>{{ summary.zeroDays }}</strong></div>
      <div class="cache-stat-card"><span>未覆盖日期</span><strong>{{ summary.missingDays }}</strong></div>
      <div class="cache-stat-card"><span>缓存记录</span><strong>{{ formatNumber(summary.totalRecords) }}</strong></div>
    </section>

    <section v-if="progress" class="cache-task-line">
      <div>
        <strong>当前任务：</strong>{{ progress.status || '--' }}
        <span v-if="progress.message">｜{{ progress.message }}</span>
      </div>
      <el-progress :percentage="Number(progress.progress_percent || 0)" :stroke-width="8" />
    </section>

    <section class="table-panel cache-admin-table">
      <div class="panel-title">
        <div><h3>逐日缓存状态</h3></div>
        <span>{{ days.length }} 天</span>
      </div>
      <el-table v-loading="scanLoading" :data="days" border stripe class="monitor-table" height="620" empty-text="暂无缓存扫描结果">
        <el-table-column prop="date" label="日期" width="120" fixed />
        <el-table-column label="状态" width="130">
          <template #default="scope"><el-tag :type="statusType(scope.row.status)" effect="dark">{{ statusText(scope.row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="record_count" label="记录数" width="105" sortable />
        <el-table-column prop="first_time" label="首条时间" min-width="170" />
        <el-table-column prop="last_time" label="末条时间" min-width="170" />
        <el-table-column prop="active_hour_count" label="活跃小时" width="105" sortable />
        <el-table-column label="小时分布" min-width="240"><template #default="scope">{{ activeHourText(scope.row) }}</template></el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="scope">
            <el-button size="small" @click="openDay(scope.row)">详情</el-button>
            <el-button size="small" type="warning" :loading="actionLoading" @click="refreshDay(scope.row)">重拉</el-button>
            <el-button size="small" type="danger" :loading="actionLoading" @click="removeDay(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-drawer v-model="drawerVisible" :title="`${selectedDate} 缓存详情`" size="88%" custom-class="cache-detail-drawer">
      <section v-loading="detailLoading" class="cache-detail-body">
        <div class="cache-detail-top">
          <div class="cache-detail-status">
            <el-tag :type="statusType(dayDetail?.status)" effect="dark">{{ statusText(dayDetail?.status) }}</el-tag>
            <span>记录数：{{ formatNumber(dayDetail?.record_count || 0) }}</span>
            <span>数据表：{{ dayDetail?.record_table || '--' }}</span>
          </div>
          <div class="cache-detail-filters">
            <el-select v-model="hourFilter" placeholder="小时" style="width: 140px" @change="() => { recordPage = 1; loadDayDetail(); }">
              <el-option label="全部小时" value="all" />
              <el-option v-for="h in 24" :key="h - 1" :label="`${String(h - 1).padStart(2, '0')}:00`" :value="h - 1" />
            </el-select>
            <el-button :loading="detailLoading" @click="loadDayDetail">刷新详情</el-button>
          </div>
        </div>

        <div class="hour-grid">
          <button
            v-for="item in detailHours"
            :key="item.hour"
            class="hour-cell"
            :class="{ active: String(hourFilter) === String(item.hour), filled: item.has_data }"
            @click="() => { hourFilter = item.hour; recordPage = 1; loadDayDetail(); }"
          >
            <span>{{ String(item.hour).padStart(2, '0') }}</span>
            <strong>{{ item.record_count }}</strong>
          </button>
        </div>

        <el-table :data="detailRecords" border stripe class="monitor-table cache-record-table" height="420" empty-text="当前条件下暂无记录">
          <el-table-column prop="create_time" label="采集时间" min-width="165" fixed />
          <el-table-column prop="wendu" label="温度" width="82" />
          <el-table-column prop="shidu" label="湿度" width="82" />
          <el-table-column prop="fengsu" label="风速" width="82" />
          <el-table-column prop="fengxiang" label="风向" width="82" />
          <el-table-column prop="pm25" label="PM2.5" width="88" />
          <el-table-column prop="pm10" label="PM10" width="88" />
          <el-table-column prop="yuliang" label="雨量" width="82" />
          <el-table-column prop="yuqiang" label="雨强" width="82" />
          <el-table-column prop="record_key" label="记录键" min-width="260" show-overflow-tooltip />
          <el-table-column label="操作" width="92" fixed="right"><template #default="scope"><el-button size="small" type="danger" @click="removeRecord(scope.row)">删除</el-button></template></el-table-column>
        </el-table>
        <div class="cache-pagination">
          <el-pagination
            background
            layout="total, sizes, prev, pager, next"
            :total="detailPagination.total"
            :current-page="recordPage"
            :page-size="recordPageSize"
            :page-sizes="[50, 100, 200, 500, 1000]"
            @current-change="onDetailPageChange"
            @size-change="onDetailSizeChange"
          />
        </div>
      </section>
    </el-drawer>
  </main>
</template>
