// Shared mock data for Auto Analytics KZ

const BRANDS = [
  { id: 1, name: 'Toyota', listings: 28420, avg: 18_400_000, delta: 2.4 },
  { id: 2, name: 'Hyundai', listings: 21330, avg: 12_200_000, delta: -0.8 },
  { id: 3, name: 'Kia', listings: 19120, avg: 11_850_000, delta: 1.1 },
  { id: 4, name: 'Lada', listings: 17840, avg: 4_850_000, delta: -3.2 },
  { id: 5, name: 'Mercedes-Benz', listings: 14200, avg: 28_900_000, delta: 4.1 },
  { id: 6, name: 'BMW', listings: 12850, avg: 24_700_000, delta: 3.7 },
  { id: 7, name: 'Volkswagen', listings: 10940, avg: 9_850_000, delta: 0.4 },
  { id: 8, name: 'Nissan', listings: 9870, avg: 10_200_000, delta: -1.5 },
  { id: 9, name: 'Lexus', listings: 8720, avg: 22_400_000, delta: 5.2 },
  { id: 10, name: 'Chevrolet', listings: 8310, avg: 5_820_000, delta: -2.1 },
  { id: 11, name: 'Honda', listings: 7620, avg: 13_200_000, delta: 1.8 },
  { id: 12, name: 'Audi', listings: 6980, avg: 19_400_000, delta: 2.9 },
];

const CITIES = [
  { name: 'Алматы',    x: 75, y: 82, listings: 94200, avg: 14_800_000 },
  { name: 'Астана',    x: 52, y: 42, listings: 61800, avg: 13_900_000 },
  { name: 'Шымкент',   x: 55, y: 88, listings: 32400, avg: 9_800_000 },
  { name: 'Караганда', x: 55, y: 55, listings: 18600, avg: 10_200_000 },
  { name: 'Актобе',    x: 24, y: 43, listings: 14200, avg: 11_400_000 },
  { name: 'Павлодар',  x: 62, y: 32, listings: 11800, avg: 11_900_000 },
  { name: 'Усть-Каменогорск', x: 82, y: 37, listings: 10400, avg: 10_600_000 },
  { name: 'Костанай',  x: 42, y: 27, listings: 9200, avg: 10_100_000 },
  { name: 'Атырау',    x: 14, y: 62, listings: 8800, avg: 13_200_000 },
  { name: 'Уральск',   x: 16, y: 42, listings: 7400, avg: 10_300_000 },
  { name: 'Семей',     x: 76, y: 42, listings: 6200, avg: 8_900_000 },
  { name: 'Тараз',     x: 60, y: 85, listings: 5900, avg: 9_400_000 },
  { name: 'Кызылорда', x: 42, y: 75, listings: 4800, avg: 8_600_000 },
  { name: 'Актау',     x: 8,  y: 74, listings: 4200, avg: 14_100_000 },
];

const PROFIT_MODELS = [
  { brand: 'Toyota', model: 'Camry', gen: 'XV70', year: '2018–21', buy: 14_200_000, sell: 17_400_000, margin: 22.5, days: 12, vol: 1840, risk: 'low' },
  { brand: 'Lexus', model: 'RX 350', gen: 'AL20', year: '2017–19', buy: 19_800_000, sell: 24_300_000, margin: 22.7, days: 18, vol: 420, risk: 'low' },
  { brand: 'Toyota', model: 'Land Cruiser Prado', gen: '150', year: '2014–17', buy: 21_500_000, sell: 26_900_000, margin: 25.1, days: 16, vol: 680, risk: 'low' },
  { brand: 'Hyundai', model: 'Tucson', gen: 'NX4', year: '2021–23', buy: 13_400_000, sell: 15_900_000, margin: 18.6, days: 14, vol: 720, risk: 'low' },
  { brand: 'Kia', model: 'Sportage', gen: 'NQ5', year: '2021–23', buy: 13_800_000, sell: 16_400_000, margin: 18.8, days: 15, vol: 610, risk: 'low' },
  { brand: 'BMW', model: 'X5', gen: 'G05', year: '2018–21', buy: 26_200_000, sell: 31_800_000, margin: 21.3, days: 24, vol: 310, risk: 'medium' },
  { brand: 'Mercedes-Benz', model: 'E-Class', gen: 'W213', year: '2016–19', buy: 19_200_000, sell: 23_400_000, margin: 21.8, days: 22, vol: 380, risk: 'medium' },
  { brand: 'Honda', model: 'CR-V', gen: 'RW', year: '2017–20', buy: 14_800_000, sell: 17_500_000, margin: 18.2, days: 17, vol: 240, risk: 'low' },
  { brand: 'Nissan', model: 'X-Trail', gen: 'T32', year: '2017–20', buy: 10_900_000, sell: 12_800_000, margin: 17.4, days: 19, vol: 420, risk: 'low' },
  { brand: 'Volkswagen', model: 'Tiguan', gen: 'AD1', year: '2017–20', buy: 11_400_000, sell: 13_200_000, margin: 15.8, days: 23, vol: 180, risk: 'medium' },
  { brand: 'Lada', model: 'Granta', gen: 'FL', year: '2019–22', buy: 3_800_000, sell: 4_400_000, margin: 15.8, days: 9, vol: 920, risk: 'low' },
  { brand: 'Kia', model: 'Rio', gen: 'YB', year: '2017–20', buy: 6_200_000, sell: 7_400_000, margin: 19.4, days: 11, vol: 540, risk: 'low' },
];

// Price history: daily avg for 90 days, in 1000 KZT
function makePriceSeries(start, trend, noise, days = 90) {
  const out = [];
  let v = start;
  for (let i = 0; i < days; i++) {
    v += trend + (Math.sin(i / 6) * noise) + (Math.cos(i / 13) * noise * 0.6);
    v += (Math.random() - 0.5) * noise * 0.4;
    out.push({ day: i, value: Math.round(v) });
  }
  return out;
}

const PRICE_INDEX = makePriceSeries(100, 0.12, 0.8); // index normalized
const USDKZT = makePriceSeries(512, 0.14, 1.1);

// Heatmap: rows = year (2024..2010), cols = mileage buckets (0-20, 20-50, 50-100, 100-150, 150-200, 200+)
const MILEAGE_BUCKETS = ['0–20', '20–50', '50–100', '100–150', '150–200', '200+'];
const YEARS = [2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 2015, 2014, 2013, 2012, 2010];

// price in млн ₸ — depreciation curve
function heatmapPrice(year, mIdx) {
  const ageFactor = Math.pow(0.88, 2024 - year);
  const mileageFactor = [1.05, 1.0, 0.86, 0.72, 0.58, 0.44][mIdx];
  const base = 28;
  return +(base * ageFactor * mileageFactor).toFixed(1);
}
function heatmapVolume(year, mIdx) {
  const ageF = Math.max(0, 1 - Math.abs(year - 2018) / 15);
  const mF = [0.2, 0.5, 1, 0.9, 0.7, 0.4][mIdx];
  return Math.round(1200 * ageF * mF);
}

// Funnel: days-on-market buckets
const FUNNEL = [
  { label: '0–3 дня',   count: 3840, color: 'var(--up)',     note: 'быстрые продажи' },
  { label: '4–7 дней',  count: 6120, color: '#5fd99a',      note: 'активный спрос' },
  { label: '8–14 дней', count: 8450, color: '#a3d06a',      note: 'норма' },
  { label: '15–30 дней', count: 9820, color: 'var(--accent)', note: 'норма' },
  { label: '31–60 дней', count: 7240, color: '#e89050',      note: 'замедление' },
  { label: '61–90 дней', count: 4380, color: '#e06872',      note: 'низкая ликвидность' },
  { label: '90+ дней',  count: 2920, color: 'var(--down)',   note: 'застой' },
];

const SOURCES = [
  { name: 'kolesa.kz', count: 128400, color: '#6ea8ff' },
  { name: 'mycar.kz', count: 21800, color: '#22e0a1' },
  { name: 'olx.kz', count: 8200, color: '#f4b84a' },
  { name: 'avtorynok.kz', count: 2400, color: '#b47bff' },
  { name: 'newauto.kz', count: 840, color: '#ff8aa3' },
];

// Recent listings feed
const RECENT_LISTINGS = [
  { id: 'kolesa-ad-184829421', brand: 'Toyota', model: 'Camry', year: 2019, price: 16_800_000, mileage: 78, city: 'Алматы', src: 'kolesa', minutes: 2, delta: -400_000 },
  { id: 'kolesa-ad-184829345', brand: 'Kia', model: 'K5', year: 2022, price: 15_200_000, mileage: 32, city: 'Астана', src: 'kolesa', minutes: 3, delta: 0 },
  { id: 'mycar-19284', brand: 'Hyundai', model: 'Tucson', year: 2021, price: 14_900_000, mileage: 45, city: 'Шымкент', src: 'mycar', minutes: 6, delta: -200_000 },
  { id: 'olx-IDqMNxR', brand: 'Lada', model: 'Vesta', year: 2020, price: 4_800_000, mileage: 68, city: 'Караганда', src: 'olx', minutes: 8, delta: 100_000 },
  { id: 'kolesa-ad-184820189', brand: 'BMW', model: 'X5', year: 2020, price: 28_400_000, mileage: 54, city: 'Алматы', src: 'kolesa', minutes: 11, delta: -1_200_000 },
  { id: 'kolesa-ad-184819833', brand: 'Lexus', model: 'RX 350', year: 2019, price: 23_700_000, mileage: 72, city: 'Астана', src: 'kolesa', minutes: 13, delta: 0 },
  { id: 'mycar-19228', brand: 'Mercedes-Benz', model: 'GLE', year: 2020, price: 32_100_000, mileage: 48, city: 'Алматы', src: 'mycar', minutes: 15, delta: -500_000 },
  { id: 'olx-IDqMAvR', brand: 'Honda', model: 'CR-V', year: 2018, price: 13_400_000, mileage: 102, city: 'Актобе', src: 'olx', minutes: 18, delta: 0 },
];

// Model-specific series (for detail page)
const CAMRY_SERIES = makePriceSeries(16200, -4.2, 85);
const CAMRY_VOLUME = Array.from({length: 90}, (_, i) => 120 + Math.round(Math.sin(i/4)*20 + Math.random()*30));
const CAMRY_LISTINGS = [
  { year: 2023, mileage: 18, price: 19_400_000, city: 'Алматы', days: 4 },
  { year: 2022, mileage: 32, price: 17_800_000, city: 'Астана', days: 7 },
  { year: 2021, mileage: 48, price: 16_400_000, city: 'Алматы', days: 12 },
  { year: 2020, mileage: 62, price: 14_900_000, city: 'Шымкент', days: 18 },
  { year: 2020, mileage: 71, price: 14_200_000, city: 'Караганда', days: 24 },
  { year: 2019, mileage: 84, price: 13_200_000, city: 'Алматы', days: 9 },
  { year: 2019, mileage: 98, price: 12_400_000, city: 'Актобе', days: 31 },
  { year: 2018, mileage: 112, price: 11_200_000, city: 'Астана', days: 14 },
];

const PRICE_HISTORY_MOCK = [
  { date: '21 апр 2026', price: 16_800_000, delta: -400_000 },
  { date: '14 апр 2026', price: 17_200_000, delta: 0 },
  { date: '01 апр 2026', price: 17_200_000, delta: -300_000 },
  { date: '18 мар 2026', price: 17_500_000, delta: 0 },
  { date: '05 мар 2026', price: 17_500_000, delta: -200_000 },
  { date: '20 фев 2026', price: 17_700_000, delta: 0 },
];

// Exports
Object.assign(window, {
  BRANDS, CITIES, PROFIT_MODELS,
  PRICE_INDEX, USDKZT,
  MILEAGE_BUCKETS, YEARS, heatmapPrice, heatmapVolume,
  FUNNEL, SOURCES, RECENT_LISTINGS,
  CAMRY_SERIES, CAMRY_VOLUME, CAMRY_LISTINGS, PRICE_HISTORY_MOCK,
});
