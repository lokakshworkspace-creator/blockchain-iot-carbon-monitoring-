// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title CarbonMonitor
/// @notice Anchors a SHA-256 hash of each off-chain sensor record (stored in
/// MongoDB) so tampering with that data can later be detected by re-hashing
/// it and comparing against what's recorded here. This contract only
/// stores and returns hashes - the comparison itself happens off-chain in
/// Python (Gateway/verification.py). There is deliberately no on-chain
/// verifyHash(): keeping that logic off-chain avoids paying gas for a
/// check that Python can do for free.
contract CarbonMonitor {
    event HashStored(uint indexed recordId, bytes32 hash, uint256 timestamp);

    uint private _nextRecordId;
    mapping(uint => bytes32) private _hashes;

    /// @notice Stores a new hash under an auto-incrementing record id.
    /// @param hash The SHA-256 hash of one sensor record (device_id + co2 +
    /// sensor_timestamp), as raw bytes32 rather than a hex string.
    /// @return recordId The id this hash was stored under.
    function storeHash(bytes32 hash) external returns (uint recordId) {
        recordId = _nextRecordId;
        _hashes[recordId] = hash;
        _nextRecordId += 1;
        emit HashStored(recordId, hash, block.timestamp);
    }

    /// @notice Returns the hash stored under a given record id (bytes32(0)
    /// if nothing was ever stored under it).
    function getHash(uint recordId) external view returns (bytes32) {
        return _hashes[recordId];
    }
}
