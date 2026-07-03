import dayjs from 'dayjs';
import { apiClient } from './client.js';

export function getDefaultTimeRange() {
  return [
    dayjs().subtract(13, 'day').startOf('day').format('YYYY-MM-DD HH:mm:ss'),
    dayjs().endOf('day').format('YYYY-MM-DD HH:mm:ss'),
  ];
}

export function formatTimeRangeText(range) {
  if (!Array.isArray(range) || range.length !== 2) return '未选择时间区间';
  const start = dayjs(range[0]);
  const end = dayjs(range[1]);
  if (!start.isValid() || !end.isValid()) return '未选择时间区间';
  return `${start.format('YYYY-MM-DD HH:mm:ss')} 至 ${end.format('YYYY-MM-DD HH:mm:ss')}`;
}

export function toMillisecondString(value) {
  if (!value) return '';
  if (typeof value === 'number') return String(value);
  if (value instanceof Date) return String(value.getTime());
  const parsed = dayjs(value);
  return parsed.isValid() ? String(parsed.valueOf()) : String(value);
}

function normaliseCacheParams({ startTime, endTime, page = 1, pageSize = 20 } = {}) {
  const defaultRange = getDefaultTimeRange();
  return {
    startTime: toMillisecondString(startTime || defaultRange[0]),
    endTime: toMillisecondString(endTime || defaultRange[1]),
    page: Number(page || 1),
    pageSize: Number(pageSize || 20),
  };
}

export async function fetchHealth() {
  return apiClient.get('/borad/health');
}

export async function fetchCacheStatus() {
  return apiClient.get('/borad/cache/status');
}

export async function fetchCacheProgress() {
  return apiClient.get('/borad/cache/progress');
}

export async function triggerCachePrefetch({ startTime, endTime, forceRefresh = false } = {}) {
  const params = {};
  if (startTime) params.start_time = toMillisecondString(startTime);
  if (endTime) params.end_time = toMillisecondString(endTime);
  if (forceRefresh) params.force_refresh = '1';
  return apiClient.get('/borad/cache/prefetch', { params });
}

export async function fetchWeatherData({ startTime, endTime, page = 1, pageSize = 20, forceRefresh = false } = {}) {
  const p = normaliseCacheParams({ startTime, endTime, page, pageSize });
  return apiClient.get(`/borad/${p.page}/${p.pageSize}`, {
    params: {
      start_time: p.startTime,
      end_time: p.endTime,
      force_refresh: forceRefresh ? '1' : undefined,
    },
  });
}

export async function fetchCacheScan({ startTime, endTime, days = 30 } = {}) {
  const params = {};
  if (startTime) params.start_time = toMillisecondString(startTime);
  if (endTime) params.end_time = toMillisecondString(endTime);
  if (!startTime && !endTime && days) params.days = days;
  return apiClient.get('/borad/cache/scan', { params });
}

export async function fetchCacheDayDetail(date, { hour = null, page = 1, pageSize = 100 } = {}) {
  const params = { page, page_size: pageSize };
  if (hour !== null && hour !== undefined && hour !== '') params.hour = hour;
  return apiClient.get(`/borad/cache/day/${date}`, { params });
}

export async function refreshCacheDay(date) {
  return apiClient.post(`/borad/cache/day/${date}/refresh`, null, { params: { force_refresh: '1' } });
}

export async function deleteCacheDay(date) {
  return apiClient.delete(`/borad/cache/day/${date}/delete`);
}

export async function deleteCacheRecord(recordKey) {
  return apiClient.delete(`/borad/cache/record/${recordKey}/delete`);
}
