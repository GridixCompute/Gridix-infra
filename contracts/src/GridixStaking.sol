// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title GridixStaking — provider collateral, slashing (with dispute hold), and batch payouts.
/// @notice Providers stake USDC as collateral. Unstaking has a cooldown so a caught provider
///         can't escape before the detection+dispute window closes. The coordinator can slash
///         (only into a HELD dispute, never an instant burn) and settle many providers' earnings
///         in one transaction; providers withdraw their own earnings (and pay their own gas).
/// @dev Balances by bucket — active stake, cooling (unstaking), held-in-dispute, earnings, and
///      the settlement pool. Invariant: token.balanceOf(this) == the sum of all five. USDC-only
///      (unit-exact, no fee-on-transfer).
contract GridixStaking is AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    /// @notice May slash and settle (the coordinator). Separate from admin and arbiter.
    bytes32 public constant COORDINATOR_ROLE = keccak256("COORDINATOR_ROLE");
    /// @notice May resolve disputes (the arbiter). Separate from the party that slashes.
    bytes32 public constant ARBITER_ROLE = keccak256("ARBITER_ROLE");

    IERC20 public immutable token;

    /// @notice Minimum stake for a provider to be eligible (enforced off-chain by the matcher).
    uint256 public minStake;
    /// @notice Unstake cooldown. Must exceed the off-chain detection + dispute window (Session 10)
    ///         so a cheating provider can be slashed before their collateral leaves.
    uint256 public cooldownPeriod;
    /// @notice Destination for upheld (executed) slashes.
    address public treasury;
    /// @notice USDC available to pay out via settleBatch (funded by depositSettlement).
    uint256 public settlementPool;

    struct Unstaking {
        uint256 amount;
        uint256 unlockAt;
    }

    struct Dispute {
        uint256 amount;
        bytes32 evidenceHash;
        bool open;
    }

    mapping(address => uint256) private _stake; // active collateral
    mapping(address => Unstaking) private _unstaking; // cooling down, still slashable
    mapping(address => Dispute) private _dispute; // slashed, held pending resolution
    mapping(address => uint256) private _earnings; // settled, provider-withdrawable

    event Staked(address indexed provider, uint256 amount);
    event UnstakeRequested(address indexed provider, uint256 amount, uint256 unlockAt);
    event Unstaked(address indexed provider, uint256 amount);
    event Slashed(address indexed provider, uint256 amount, bytes32 indexed evidenceHash);
    event DisputeResolved(address indexed provider, bool upheld, uint256 amount);
    event Settled(address indexed provider, uint256 amount);
    event Withdrawn(address indexed provider, uint256 amount);
    event SettlementFunded(address indexed from, uint256 amount);
    event MinStakeUpdated(uint256 minStake);
    event CooldownUpdated(uint256 cooldownPeriod);
    event TreasuryUpdated(address indexed treasury);

    error ZeroAmount();
    error ZeroAddress();
    error InsufficientStake(uint256 requested, uint256 available);
    error CooldownActive(uint256 unlockAt);
    error NothingUnstaking();
    error DisputeAlreadyOpen();
    error NoOpenDispute();
    error LengthMismatch();
    error InsufficientSettlementFunds(uint256 requested, uint256 available);
    error NothingToWithdraw();

    constructor(
        address token_,
        address admin_,
        address coordinator_,
        address arbiter_,
        address treasury_,
        uint256 minStake_,
        uint256 cooldownPeriod_
    ) {
        if (
            token_ == address(0) || admin_ == address(0) || coordinator_ == address(0) || arbiter_ == address(0)
                || treasury_ == address(0)
        ) {
            revert ZeroAddress();
        }
        token = IERC20(token_);
        treasury = treasury_;
        minStake = minStake_;
        cooldownPeriod = cooldownPeriod_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin_);
        _grantRole(COORDINATOR_ROLE, coordinator_);
        _grantRole(ARBITER_ROLE, arbiter_);
    }

    // ── views ────────────────────────────────────────────────────────────────────

    function stakeOf(address provider) external view returns (uint256) {
        return _stake[provider];
    }

    function unstakingOf(address provider) external view returns (uint256 amount, uint256 unlockAt) {
        Unstaking storage u = _unstaking[provider];
        return (u.amount, u.unlockAt);
    }

    function disputeOf(address provider) external view returns (uint256 amount, bytes32 evidenceHash, bool open) {
        Dispute storage d = _dispute[provider];
        return (d.amount, d.evidenceHash, d.open);
    }

    function earningsOf(address provider) external view returns (uint256) {
        return _earnings[provider];
    }

    /// @notice Whether a provider meets the minimum stake (the matcher gate, on-chain-readable).
    function hasMinimumStake(address provider) external view returns (bool) {
        return _stake[provider] >= minStake;
    }

    // ── staking ──────────────────────────────────────────────────────────────────

    function stake(uint256 amount) external whenNotPaused nonReentrant {
        if (amount == 0) revert ZeroAmount();
        _stake[msg.sender] += amount;
        emit Staked(msg.sender, amount);
        token.safeTransferFrom(msg.sender, address(this), amount);
    }

    /// @notice Begin unstaking `amount`: it stops backing new work but stays slashable until the
    ///         cooldown elapses. Adding to a pending request restarts the cooldown (no nibbling
    ///         collateral out ahead of a slash).
    function unstake(uint256 amount) external whenNotPaused nonReentrant {
        if (amount == 0) revert ZeroAmount();
        uint256 active = _stake[msg.sender];
        if (amount > active) revert InsufficientStake(amount, active);
        _stake[msg.sender] = active - amount;
        Unstaking storage u = _unstaking[msg.sender];
        u.amount += amount;
        u.unlockAt = block.timestamp + cooldownPeriod;
        emit UnstakeRequested(msg.sender, amount, u.unlockAt);
    }

    /// @notice Claim unstaked collateral once the cooldown has passed.
    function completeUnstake() external whenNotPaused nonReentrant {
        Unstaking storage u = _unstaking[msg.sender];
        uint256 amount = u.amount;
        if (amount == 0) revert NothingUnstaking();
        if (block.timestamp < u.unlockAt) revert CooldownActive(u.unlockAt);
        delete _unstaking[msg.sender];
        emit Unstaked(msg.sender, amount);
        token.safeTransfer(msg.sender, amount);
    }

    // ── slashing + dispute hold (Session 10) ─────────────────────────────────────

    /// @notice Slash `amount` of a provider's collateral into a HELD dispute keyed to an
    ///         off-chain evidence hash (Session 10 fraud-proof trail). Not burned until resolved.
    ///         COORDINATOR_ROLE only. One open dispute per provider at a time.
    function slash(address provider, uint256 amount, bytes32 evidenceHash)
        external
        nonReentrant
        onlyRole(COORDINATOR_ROLE)
    {
        if (amount == 0) revert ZeroAmount();
        if (_dispute[provider].open) revert DisputeAlreadyOpen();
        uint256 active = _stake[provider];
        uint256 cooling = _unstaking[provider].amount;
        uint256 slashable = active + cooling;
        if (amount > slashable) revert InsufficientStake(amount, slashable);
        // Take from active stake first, then from the cooling (unstaking) bucket.
        if (amount <= active) {
            _stake[provider] = active - amount;
        } else {
            _stake[provider] = 0;
            _unstaking[provider].amount = cooling - (amount - active);
        }
        _dispute[provider] = Dispute({amount: amount, evidenceHash: evidenceHash, open: true});
        emit Slashed(provider, amount, evidenceHash);
    }

    /// @notice Resolve a held slash. `upheld` executes it (funds to treasury); otherwise the
    ///         held collateral returns to the provider's active stake. ARBITER_ROLE only.
    function resolveDispute(address provider, bool upheld) external nonReentrant onlyRole(ARBITER_ROLE) {
        Dispute storage d = _dispute[provider];
        if (!d.open) revert NoOpenDispute();
        uint256 amount = d.amount;
        d.open = false;
        emit DisputeResolved(provider, upheld, amount);
        if (upheld) {
            token.safeTransfer(treasury, amount);
        } else {
            _stake[provider] += amount;
        }
    }

    // ── batch settlement ─────────────────────────────────────────────────────────

    /// @notice Fund the settlement pool (pull USDC from the caller).
    function depositSettlement(uint256 amount) external whenNotPaused nonReentrant {
        if (amount == 0) revert ZeroAmount();
        settlementPool += amount;
        emit SettlementFunded(msg.sender, amount);
        token.safeTransferFrom(msg.sender, address(this), amount);
    }

    /// @notice Credit N providers' earnings in one transaction — the gas win. No token transfer
    ///         happens here; each provider calls withdraw() and pays their own gas. COORDINATOR
    ///         only. Reverts on array mismatch or if the total exceeds the settlement pool.
    function settleBatch(address[] calldata providers, uint256[] calldata amounts)
        external
        nonReentrant
        whenNotPaused
        onlyRole(COORDINATOR_ROLE)
    {
        uint256 n = providers.length;
        if (n != amounts.length) revert LengthMismatch();
        uint256 total;
        for (uint256 i = 0; i < n; i++) {
            total += amounts[i];
        }
        uint256 pool = settlementPool;
        if (total > pool) revert InsufficientSettlementFunds(total, pool);
        settlementPool = pool - total;
        for (uint256 i = 0; i < n; i++) {
            _earnings[providers[i]] += amounts[i];
            emit Settled(providers[i], amounts[i]);
        }
    }

    /// @notice Withdraw the caller's settled earnings.
    function withdraw() external whenNotPaused nonReentrant {
        uint256 amount = _earnings[msg.sender];
        if (amount == 0) revert NothingToWithdraw();
        _earnings[msg.sender] = 0;
        emit Withdrawn(msg.sender, amount);
        token.safeTransfer(msg.sender, amount);
    }

    // ── admin ────────────────────────────────────────────────────────────────────

    function setMinStake(uint256 minStake_) external onlyRole(DEFAULT_ADMIN_ROLE) {
        minStake = minStake_;
        emit MinStakeUpdated(minStake_);
    }

    function setCooldownPeriod(uint256 cooldownPeriod_) external onlyRole(DEFAULT_ADMIN_ROLE) {
        cooldownPeriod = cooldownPeriod_;
        emit CooldownUpdated(cooldownPeriod_);
    }

    function setTreasury(address treasury_) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (treasury_ == address(0)) revert ZeroAddress();
        treasury = treasury_;
        emit TreasuryUpdated(treasury_);
    }

    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }
}
