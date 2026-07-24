import { useState } from 'react'
import './App.css'
import Schedule from './Schedule'
import Squad from './Squad'
import Injuries from './Injuries'

const TABS = [
  { key: 'schedule', label: 'Jadwal', Component: Schedule },
  { key: 'squad', label: 'Skuad', Component: Squad },
  { key: 'injuries', label: 'Cedera', Component: Injuries },
]

function App() {
  const [activeTab, setActiveTab] = useState('schedule')
  const ActiveComponent = TABS.find((tab) => tab.key === activeTab).Component

  return (
    <div className="page">
      <header className="page-header">
        <h1>MU Analytics</h1>
        <p>IndoManUtd Jogja</p>
      </header>

      <nav className="tab-nav">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={tab.key === activeTab ? 'tab-button active' : 'tab-button'}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main>
        <ActiveComponent />
      </main>
    </div>
  )
}

export default App
