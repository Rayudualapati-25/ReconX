import { describe, expect, it } from 'vitest'

import { formatDate, formatDuration, formatMoney, formatPercent } from './format'

describe('formatMoney', () => {
  it.each([
    ['5.00', '₹5.00'],
    ['999.50', '₹999.50'],
    ['1000.00', '₹1,000.00'],
    ['123456.78', '₹1,23,456.78'],
    ['12345678.90', '₹1,23,45,678.90'],
    ['-25000.00', '−₹25,000.00'],
    ['42', '₹42.00'],
  ])('formats %s as %s with Indian digit grouping', (amount, expected) => {
    expect(formatMoney(amount)).toBe(expected)
  })
})

describe('other formats', () => {
  it('shows a rate as a percentage with two decimals', () => {
    expect(formatPercent(0.94204)).toBe('94.20%')
  })

  it('shows a date as day, short month and year, whatever the time zone', () => {
    expect(formatDate('2026-10-01')).toBe('01 Oct 2026')
    expect(formatDate('2026-10-28T23:59:00+00:00')).toBe('28 Oct 2026')
  })

  it('shows short durations in milliseconds and long ones in seconds', () => {
    expect(formatDuration(412)).toBe('412 ms')
    expect(formatDuration(1873)).toBe('1.87 s')
  })
})
