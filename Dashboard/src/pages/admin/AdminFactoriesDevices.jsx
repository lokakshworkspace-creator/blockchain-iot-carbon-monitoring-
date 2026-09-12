/**
 * Factories & Devices tab of the admin panel: two independent
 * list+create sections. Device rows show is_hardware as a read-only
 * badge only in this phase (no PATCH-wired toggle control yet - the
 * brief calls this out explicitly as "display only" for now).
 */

import { useEffect, useState } from 'react'

import {
  adminCreateDevice,
  adminCreateFactory,
  adminListDevices,
  adminListFactories,
  adminListRegions,
} from '../../services/api.js'

const EMPTY_FACTORY_FORM = { name: '', regionId: '', location: '', isSimulated: false }
const EMPTY_DEVICE_FORM = { deviceId: '', factoryId: '', isHardware: false }

export default function AdminFactoriesDevices() {
  const [factories, setFactories] = useState([])
  const [devices, setDevices] = useState([])
  const [regions, setRegions] = useState([])
  const [error, setError] = useState(null)
  const [factoryForm, setFactoryForm] = useState(EMPTY_FACTORY_FORM)
  const [deviceForm, setDeviceForm] = useState(EMPTY_DEVICE_FORM)
  const [pending, setPending] = useState(false)

  function refresh() {
    adminListFactories()
      .then(setFactories)
      .catch((err) => setError(err.message))
    adminListDevices()
      .then(setDevices)
      .catch((err) => setError(err.message))
  }

  useEffect(() => {
    refresh()
    adminListRegions()
      .then(setRegions)
      .catch(() => {})
  }, [])

  async function handleCreateFactory(event) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await adminCreateFactory({
        name: factoryForm.name,
        regionId: factoryForm.regionId,
        isSimulated: factoryForm.isSimulated,
        location: factoryForm.location,
      })
      setFactoryForm(EMPTY_FACTORY_FORM)
      refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  async function handleCreateDevice(event) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await adminCreateDevice({
        deviceId: deviceForm.deviceId,
        factoryId: deviceForm.factoryId,
        isHardware: deviceForm.isHardware,
      })
      setDeviceForm(EMPTY_DEVICE_FORM)
      refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  const regionName = (id) => regions.find((r) => r.id === id)?.name ?? id
  const factoryName = (id) => factories.find((f) => f.id === id)?.name ?? id

  return (
    <>
      <section className="section">
        <h2>Factories</h2>
        {error && <div className="empty error-text">{error}</div>}

        <form className="card card-pad admin-form" onSubmit={handleCreateFactory}>
          <input
            className="input"
            placeholder="Name"
            value={factoryForm.name}
            onChange={(event) => setFactoryForm({ ...factoryForm, name: event.target.value })}
            required
          />
          <select
            className="device-select"
            value={factoryForm.regionId}
            onChange={(event) => setFactoryForm({ ...factoryForm, regionId: event.target.value })}
            required
          >
            <option value="">Select a region…</option>
            {regions.map((region) => (
              <option key={region.id} value={region.id}>
                {region.name}
              </option>
            ))}
          </select>
          <input
            className="input"
            placeholder="Location (optional)"
            value={factoryForm.location}
            onChange={(event) => setFactoryForm({ ...factoryForm, location: event.target.value })}
          />
          <label className="admin-checkbox">
            <input
              type="checkbox"
              checked={factoryForm.isSimulated}
              onChange={(event) => setFactoryForm({ ...factoryForm, isSimulated: event.target.checked })}
            />
            Simulated
          </label>
          <button type="submit" className="btn-verify" disabled={pending}>
            {pending ? 'Creating…' : 'Create factory'}
          </button>
        </form>

        <div className="card">
          {factories.length === 0 ? (
            <div className="empty">No factories yet.</div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Region</th>
                  <th>Location</th>
                  <th>Simulated</th>
                </tr>
              </thead>
              <tbody>
                {factories.map((factory) => (
                  <tr key={factory.id}>
                    <td>{factory.name}</td>
                    <td className="dim">{regionName(factory.region_id)}</td>
                    <td className="dim">{factory.location || '—'}</td>
                    <td>
                      <span className={factory.is_simulated ? 'badge badge-pending' : 'badge badge-online'}>
                        {factory.is_simulated ? 'Simulated' : 'Real'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="section">
        <h2>Devices</h2>

        <form className="card card-pad admin-form" onSubmit={handleCreateDevice}>
          <input
            className="input"
            placeholder="Device ID (MQTT identity)"
            value={deviceForm.deviceId}
            onChange={(event) => setDeviceForm({ ...deviceForm, deviceId: event.target.value })}
            required
          />
          <select
            className="device-select"
            value={deviceForm.factoryId}
            onChange={(event) => setDeviceForm({ ...deviceForm, factoryId: event.target.value })}
            required
          >
            <option value="">Select a factory…</option>
            {factories.map((factory) => (
              <option key={factory.id} value={factory.id}>
                {factory.name}
              </option>
            ))}
          </select>
          <label className="admin-checkbox">
            <input
              type="checkbox"
              checked={deviceForm.isHardware}
              onChange={(event) => setDeviceForm({ ...deviceForm, isHardware: event.target.checked })}
            />
            Real hardware
          </label>
          <button type="submit" className="btn-verify" disabled={pending}>
            {pending ? 'Registering…' : 'Register device'}
          </button>
        </form>

        <div className="card">
          {devices.length === 0 ? (
            <div className="empty">No devices registered yet.</div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Device ID</th>
                  <th>Factory</th>
                  <th>Type</th>
                </tr>
              </thead>
              <tbody>
                {devices.map((device) => (
                  <tr key={device.id}>
                    <td className="mono">{device.device_id}</td>
                    <td className="dim">{factoryName(device.factory_id)}</td>
                    <td>
                      <span className={device.is_hardware ? 'badge badge-online' : 'badge badge-pending'}>
                        {device.is_hardware ? 'Hardware' : 'Simulated'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </>
  )
}
