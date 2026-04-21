// lib/api.ts — Axios instance и API helper functions
import axios from 'axios';

const api = axios.create({
    baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    headers: { 'Content-Type': 'application/json' },
    paramsSerializer: (params) => {
        const searchParams = new URLSearchParams();
        for (const [key, value] of Object.entries(params)) {
            if (Array.isArray(value)) {
                value.forEach(v => searchParams.append(key, v.toString()));
            } else if (value !== undefined && value !== null) {
                searchParams.append(key, value.toString());
            }
        }
        return searchParams.toString();
    }
});

// Attach JWT token if present
api.interceptors.request.use((config) => {
    if (typeof window !== 'undefined') {
        const token = localStorage.getItem('access_token');
        if (token) config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

export const analyticsApi = {
    getSummary: (params?: Record<string, unknown>) => api.get('/api/v1/analytics/summary', { params }).then((r: any) => r.data),
    getBrands: () => api.get('/api/v1/analytics/brands').then((r: any) => r.data),
    getModels: (brandId: number) => api.get('/api/v1/analytics/models', { params: { brand_id: brandId } }).then((r: any) => r.data),
    getPriceHistory: (params: Record<string, unknown>) => api.get('/api/v1/analytics/price-history', { params }).then((r: any) => r.data),
    getMarketOverview: (params?: Record<string, unknown>) => api.get('/api/v1/analytics/market-overview', { params }).then((r: any) => r.data),
    getProfitability: (params: Record<string, unknown>) => api.get('/api/v1/analytics/profitability', { params }).then((r: any) => r.data),
    getPriceBoxplot: (params?: Record<string, unknown>) => api.get('/api/v1/analytics/price-boxplot', { params }).then((r: any) => r.data),
    // Trading-terminal endpoints
    getHeatmap: (params?: Record<string, unknown>) => api.get('/api/v1/analytics/heatmap', { params }).then((r: any) => r.data),
    getLiquidity: (params?: Record<string, unknown>) => api.get('/api/v1/analytics/liquidity', { params }).then((r: any) => r.data),
    getRecent: (params?: Record<string, unknown>) => api.get('/api/v1/analytics/recent', { params }).then((r: any) => r.data),
    getCities: () => api.get('/api/v1/analytics/cities').then((r: any) => r.data),
};

export const authApi = {
    register: (data: { email: string; password: string; full_name?: string }) =>
        api.post('/api/v1/auth/register', data).then((r: any) => r.data),
    login: (email: string, password: string) => {
        const form = new URLSearchParams();
        form.append('username', email); form.append('password', password);
        return api.post('/api/v1/auth/login', form, { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }).then((r: any) => r.data);
    },
    me: () => api.get('/api/v1/auth/me').then((r: any) => r.data),
};

export default api;
