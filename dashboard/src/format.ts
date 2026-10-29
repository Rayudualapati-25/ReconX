// Display formatting. Amounts stay strings until this point and are grouped the Indian way
// (₹1,23,456.78) by splitting the digits, so no amount is ever parsed into a float.

export function formatMoney(amount: string): string {
  const negative = amount.startsWith('-')
  const [whole, fraction = '00'] = amount.replace(/^[-+]/, '').split('.')
  const lastThree = whole.slice(-3)
  const rest = whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',')
  const grouped = rest ? `${rest},${lastThree}` : lastThree
  return `${negative ? '−' : ''}₹${grouped}.${fraction.padEnd(2, '0').slice(0, 2)}`
}

export function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(2)}%`
}

export function formatCount(count: number): string {
  return count.toLocaleString('en-IN')
}

export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.slice(0, 10).split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

export function formatDuration(milliseconds: number): string {
  return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(2)} s`
}
