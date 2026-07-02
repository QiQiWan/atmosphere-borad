import dayjs from 'dayjs';
import { apiClient } from './client.js';

export function toMillisecondString(value) {
  if (!value) return '';
  if (typeof value === 'number') return String(value);
  if (value instanceof Date) return String(value.getTime());
  const parsed = dayjs(value);
  return parsed.isValid() ? String(parsed.valueOf()) : String(value);
}

export async function fetchHealth() {
  return apiClient.get('/borad/health');
}

export async function fetchWeatherData({ startTime, endTime, page = 1, pageSize = 20 } = {}) {
  const now = Date.now();
  const start = startTime ? toMillisecondString(startTime) : String(now - 24 * 60 * 60 * 1000);
  const end = endTime ? toMillisecondString(endTime) : String(now);
  return apiClient.get(`/borad/${page}/${pageSize}`, {
    params: {
      start_time: start,
      end_time: end,
    },
  });
}
