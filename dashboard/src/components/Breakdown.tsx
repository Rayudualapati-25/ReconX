import { formatCount } from '../format'

export interface BreakdownItem<K extends string> {
  key: K
  label: string
  value: number
  detail?: string
}

interface Props<K extends string> {
  title: string
  items: BreakdownItem<K>[]
  // When set, rows are buttons that pick (or, picked again, clear) an item.
  onSelect?: (key: K | undefined) => void
  selected?: K
}

export function Breakdown<K extends string>({ title, items, onSelect, selected }: Props<K>) {
  const largest = Math.max(1, ...items.map((item) => item.value))
  return (
    <section className="panel breakdown" aria-label={title}>
      <h2 className="panel__title">{title}</h2>
      <ul className="breakdown__list">
        {items.map((item) => {
          const bar = (
            <>
              <span className="breakdown__label">{item.label}</span>
              <span className="breakdown__value">{formatCount(item.value)}</span>
              <span className="breakdown__track" aria-hidden="true">
                <span className="breakdown__bar" style={{ width: `${(item.value / largest) * 100}%` }} />
              </span>
              {item.detail && <span className="breakdown__detail">{item.detail}</span>}
            </>
          )
          return (
            <li key={item.key}>
              {onSelect ? (
                <button
                  type="button"
                  className={`breakdown__row ${selected === item.key ? 'is-selected' : ''}`}
                  aria-pressed={selected === item.key}
                  onClick={() => onSelect(selected === item.key ? undefined : item.key)}
                >
                  {bar}
                </button>
              ) : (
                <div className="breakdown__row">{bar}</div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
