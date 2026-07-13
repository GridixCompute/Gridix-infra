// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title GridixEscrow — developer-side USDC escrow for the GRIDIX compute network.
/// @notice Developers deposit USDC to fund jobs; the coordinator debits the cost of verified
///         work; developers withdraw whatever is unspent. Accounting is unit-exact (no
///         division), so USDC's 6 decimals carry no rounding risk.
/// @dev Invariant: token.balanceOf(this) == sum of all balanceOf. deposit/withdraw/debit each
///      move the token balance and a developer balance by the same amount. Fee-on-transfer
///      tokens would break this — USDC is not one, and this escrow is USDC-only.
contract GridixEscrow is AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    /// @notice Role allowed to debit developer balances (the coordinator). Deliberately
    ///         separate from DEFAULT_ADMIN_ROLE — charging funds is not administration.
    bytes32 public constant COORDINATOR_ROLE = keccak256("COORDINATOR_ROLE");

    /// @notice The escrowed token (USDC).
    IERC20 public immutable token;

    /// @notice Destination for debited funds (protocol treasury). Admin-settable.
    address public treasury;

    mapping(address => uint256) private _balances;

    event Deposited(address indexed developer, uint256 amount);
    event Withdrawn(address indexed developer, uint256 amount);
    event Debited(address indexed developer, uint256 amount, address indexed to);
    event TreasuryUpdated(address indexed treasury);

    error ZeroAmount();
    error ZeroAddress();
    error InsufficientBalance(uint256 requested, uint256 available);

    /// @param token_ USDC address.
    /// @param admin_ holder of DEFAULT_ADMIN_ROLE (manages roles, pause, treasury).
    /// @param coordinator_ holder of COORDINATOR_ROLE (may debit).
    /// @param treasury_ destination for debited funds.
    constructor(address token_, address admin_, address coordinator_, address treasury_) {
        if (token_ == address(0) || admin_ == address(0) || coordinator_ == address(0) || treasury_ == address(0)) {
            revert ZeroAddress();
        }
        token = IERC20(token_);
        treasury = treasury_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin_);
        _grantRole(COORDINATOR_ROLE, coordinator_);
    }

    /// @notice Unspent escrow balance of `developer`.
    function balanceOf(address developer) external view returns (uint256) {
        return _balances[developer];
    }

    /// @notice Deposit `amount` USDC into the caller's escrow. Caller must have approved this
    ///         contract for `amount`. Checks-effects-interactions: credit before the pull.
    function deposit(uint256 amount) external whenNotPaused nonReentrant {
        if (amount == 0) revert ZeroAmount();
        _balances[msg.sender] += amount;
        emit Deposited(msg.sender, amount);
        token.safeTransferFrom(msg.sender, address(this), amount);
    }

    /// @notice Withdraw `amount` of the caller's unspent escrow.
    function withdraw(uint256 amount) external whenNotPaused nonReentrant {
        if (amount == 0) revert ZeroAmount();
        uint256 bal = _balances[msg.sender];
        if (amount > bal) revert InsufficientBalance(amount, bal);
        _balances[msg.sender] = bal - amount;
        emit Withdrawn(msg.sender, amount);
        token.safeTransfer(msg.sender, amount);
    }

    /// @notice Debit `amount` from `developer`'s escrow to the treasury. COORDINATOR_ROLE only.
    function debit(address developer, uint256 amount) external whenNotPaused nonReentrant onlyRole(COORDINATOR_ROLE) {
        if (amount == 0) revert ZeroAmount();
        uint256 bal = _balances[developer];
        if (amount > bal) revert InsufficientBalance(amount, bal);
        _balances[developer] = bal - amount;
        address to = treasury;
        emit Debited(developer, amount, to);
        token.safeTransfer(to, amount);
    }

    /// @notice Update the treasury address. DEFAULT_ADMIN_ROLE only.
    function setTreasury(address treasury_) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (treasury_ == address(0)) revert ZeroAddress();
        treasury = treasury_;
        emit TreasuryUpdated(treasury_);
    }

    /// @notice Pause deposits/withdrawals/debits. DEFAULT_ADMIN_ROLE only.
    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    /// @notice Resume after a pause. DEFAULT_ADMIN_ROLE only.
    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }
}
