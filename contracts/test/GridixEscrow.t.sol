// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {GridixEscrow} from "../src/GridixEscrow.sol";
import {MockUSDC} from "./mocks/MockUSDC.sol";
import {ReentrantToken, IReentrancyHook} from "./mocks/ReentrantToken.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// Re-enters withdraw() from inside the token transfer callback while a withdraw is in flight.
contract ReentrancyAttacker is IReentrancyHook {
    GridixEscrow public escrow;
    ReentrantToken public token;
    uint256 public amount;

    constructor(GridixEscrow escrow_, ReentrantToken token_) {
        escrow = escrow_;
        token = token_;
    }

    function attack(uint256 amount_) external {
        amount = amount_;
        token.approve(address(escrow), amount_);
        escrow.deposit(amount_);
        token.arm(address(this)); // token will call hook() when it transfers to us
        escrow.withdraw(amount_); // interaction re-enters -> guard must revert
    }

    function hook() external override {
        escrow.withdraw(amount); // reentrant call
    }
}

contract GridixEscrowTest is Test {
    GridixEscrow internal escrow;
    MockUSDC internal usdc;

    address internal admin = makeAddr("admin");
    address internal coordinator = makeAddr("coordinator");
    address internal treasury = makeAddr("treasury");
    address internal dev = makeAddr("dev");
    address internal outsider = makeAddr("outsider");

    uint256 internal constant USDC = 1e6; // 1 USDC = 1_000_000 (6 decimals)

    // Cached in setUp so reading them can't consume a vm.prank inside an expectRevert arg.
    bytes32 internal coordRole;
    bytes32 internal adminRole;

    function setUp() public {
        usdc = new MockUSDC();
        escrow = new GridixEscrow(address(usdc), admin, coordinator, treasury);
        coordRole = escrow.COORDINATOR_ROLE();
        adminRole = escrow.DEFAULT_ADMIN_ROLE();
        usdc.mint(dev, 1000 * USDC);
        vm.prank(dev);
        usdc.approve(address(escrow), type(uint256).max);
    }

    function _deposit(address who, uint256 amount) internal {
        vm.prank(who);
        escrow.deposit(amount);
    }

    // ── happy path ───────────────────────────────────────────────────────────────

    function test_HappyPath_DepositDebitWithdraw() public {
        _deposit(dev, 100 * USDC);
        assertEq(escrow.balanceOf(dev), 100 * USDC);
        assertEq(usdc.balanceOf(address(escrow)), 100 * USDC);

        vm.prank(coordinator);
        escrow.debit(dev, 30 * USDC);
        assertEq(escrow.balanceOf(dev), 70 * USDC);
        assertEq(usdc.balanceOf(treasury), 30 * USDC); // debited funds went to treasury
        assertEq(usdc.balanceOf(address(escrow)), 70 * USDC);

        uint256 before = usdc.balanceOf(dev);
        vm.prank(dev);
        escrow.withdraw(70 * USDC);
        assertEq(escrow.balanceOf(dev), 0);
        assertEq(usdc.balanceOf(address(escrow)), 0);
        assertEq(usdc.balanceOf(dev), before + 70 * USDC);
    }

    function test_Emits_Events() public {
        vm.expectEmit(true, false, false, true, address(escrow));
        emit GridixEscrow.Deposited(dev, 5 * USDC);
        _deposit(dev, 5 * USDC);

        vm.expectEmit(true, true, false, true, address(escrow));
        emit GridixEscrow.Debited(dev, 2 * USDC, treasury);
        vm.prank(coordinator);
        escrow.debit(dev, 2 * USDC);

        vm.expectEmit(true, false, false, true, address(escrow));
        emit GridixEscrow.Withdrawn(dev, 3 * USDC);
        vm.prank(dev);
        escrow.withdraw(3 * USDC);
    }

    // ── reentrancy ───────────────────────────────────────────────────────────────

    function test_Revert_Reentrancy() public {
        ReentrantToken evil = new ReentrantToken();
        GridixEscrow evilEscrow = new GridixEscrow(address(evil), admin, coordinator, treasury);
        ReentrancyAttacker attacker = new ReentrancyAttacker(evilEscrow, evil);
        evil.mint(address(attacker), 10 * USDC);

        vm.expectRevert(ReentrancyGuard.ReentrancyGuardReentrantCall.selector);
        attacker.attack(10 * USDC);
    }

    // ── access control ───────────────────────────────────────────────────────────

    function test_Revert_DebitByNonCoordinator() public {
        _deposit(dev, 50 * USDC);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, coordRole)
        );
        vm.prank(outsider);
        escrow.debit(dev, 1 * USDC);
    }

    function test_Revert_AdminCannotDebit() public {
        // The admin holds DEFAULT_ADMIN_ROLE but NOT COORDINATOR_ROLE — roles are separate.
        _deposit(dev, 50 * USDC);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, admin, coordRole)
        );
        vm.prank(admin);
        escrow.debit(dev, 1 * USDC);
    }

    function test_RoleSeparation() public view {
        assertTrue(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), admin));
        assertTrue(escrow.hasRole(escrow.COORDINATOR_ROLE(), coordinator));
        assertFalse(escrow.hasRole(escrow.COORDINATOR_ROLE(), admin));
        assertFalse(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), coordinator));
    }

    function test_Revert_SetTreasuryByNonAdmin() public {
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, adminRole)
        );
        vm.prank(outsider);
        escrow.setTreasury(outsider);
    }

    function test_SetTreasury() public {
        address newTreasury = makeAddr("newTreasury");
        vm.expectEmit(true, false, false, false, address(escrow));
        emit GridixEscrow.TreasuryUpdated(newTreasury);
        vm.prank(admin);
        escrow.setTreasury(newTreasury);
        assertEq(escrow.treasury(), newTreasury);

        _deposit(dev, 10 * USDC);
        vm.prank(coordinator);
        escrow.debit(dev, 4 * USDC);
        assertEq(usdc.balanceOf(newTreasury), 4 * USDC);
    }

    // ── balance / bounds ─────────────────────────────────────────────────────────

    function test_Revert_WithdrawExceedsBalance() public {
        _deposit(dev, 10 * USDC);
        vm.prank(dev);
        vm.expectRevert(abi.encodeWithSelector(GridixEscrow.InsufficientBalance.selector, 11 * USDC, 10 * USDC));
        escrow.withdraw(11 * USDC);
    }

    function test_Revert_DebitExceedsBalance() public {
        _deposit(dev, 10 * USDC);
        vm.prank(coordinator);
        vm.expectRevert(abi.encodeWithSelector(GridixEscrow.InsufficientBalance.selector, 11 * USDC, 10 * USDC));
        escrow.debit(dev, 11 * USDC);
    }

    function test_Revert_ZeroAmount() public {
        vm.prank(dev);
        vm.expectRevert(GridixEscrow.ZeroAmount.selector);
        escrow.deposit(0);

        vm.prank(dev);
        vm.expectRevert(GridixEscrow.ZeroAmount.selector);
        escrow.withdraw(0);

        vm.prank(coordinator);
        vm.expectRevert(GridixEscrow.ZeroAmount.selector);
        escrow.debit(dev, 0);
    }

    function test_Revert_Constructor_ZeroAddress() public {
        vm.expectRevert(GridixEscrow.ZeroAddress.selector);
        new GridixEscrow(address(0), admin, coordinator, treasury);
        vm.expectRevert(GridixEscrow.ZeroAddress.selector);
        new GridixEscrow(address(usdc), address(0), coordinator, treasury);
        vm.expectRevert(GridixEscrow.ZeroAddress.selector);
        new GridixEscrow(address(usdc), admin, address(0), treasury);
        vm.expectRevert(GridixEscrow.ZeroAddress.selector);
        new GridixEscrow(address(usdc), admin, coordinator, address(0));
    }

    function test_Revert_SetTreasuryZeroAddress() public {
        vm.prank(admin);
        vm.expectRevert(GridixEscrow.ZeroAddress.selector);
        escrow.setTreasury(address(0));
    }

    // ── pausable ─────────────────────────────────────────────────────────────────

    function test_Revert_WhenPaused() public {
        _deposit(dev, 20 * USDC);
        vm.prank(admin);
        escrow.pause();

        vm.prank(dev);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        escrow.deposit(1 * USDC);

        vm.prank(dev);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        escrow.withdraw(1 * USDC);

        vm.prank(coordinator);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        escrow.debit(dev, 1 * USDC);
    }

    function test_Unpause_Resumes() public {
        vm.startPrank(admin);
        escrow.pause();
        escrow.unpause();
        vm.stopPrank();
        _deposit(dev, 7 * USDC);
        assertEq(escrow.balanceOf(dev), 7 * USDC);
    }

    function test_Revert_PauseByNonAdmin() public {
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, adminRole)
        );
        vm.prank(outsider);
        escrow.pause();
    }

    // ── USDC 6-decimals: unit-exact, no rounding ─────────────────────────────────

    function test_USDC6Decimals_NoRounding() public {
        assertEq(usdc.decimals(), 6);
        uint256[5] memory amounts = [uint256(1), 7, 123_456, 999_999, 1_000_001]; // sub-unit to >1 USDC
        uint256 running;
        for (uint256 i = 0; i < amounts.length; i++) {
            _deposit(dev, amounts[i]);
            running += amounts[i];
            assertEq(escrow.balanceOf(dev), running); // exact to the smallest unit
        }
        // Debit an odd sub-unit amount and withdraw the exact remainder — nothing lost.
        vm.prank(coordinator);
        escrow.debit(dev, 333_333);
        uint256 remainder = running - 333_333;
        vm.prank(dev);
        escrow.withdraw(remainder);
        assertEq(escrow.balanceOf(dev), 0);
        assertEq(usdc.balanceOf(address(escrow)), 0);
        assertEq(usdc.balanceOf(treasury), 333_333);
    }

    // ── fuzz: balance accounting invariant ───────────────────────────────────────

    function testFuzz_Accounting(uint96 depositAmt, uint96 debitAmt, uint96 withdrawAmt) public {
        uint256 dep = bound(uint256(depositAmt), 1, 1e15); // up to 1e9 USDC
        usdc.mint(dev, dep);
        vm.prank(dev);
        escrow.deposit(dep);

        uint256 deb = bound(uint256(debitAmt), 0, dep);
        if (deb > 0) {
            vm.prank(coordinator);
            escrow.debit(dev, deb);
        }

        uint256 remaining = dep - deb;
        uint256 wd = bound(uint256(withdrawAmt), 0, remaining);
        if (wd > 0) {
            vm.prank(dev);
            escrow.withdraw(wd);
        }

        uint256 expected = remaining - wd;
        // The invariant that must always hold: escrow token balance == the dev's tracked
        // balance == deposits - debits - withdrawals. No under/overflow, no drift, no leak.
        assertEq(escrow.balanceOf(dev), expected);
        assertEq(usdc.balanceOf(address(escrow)), expected);
        assertEq(usdc.balanceOf(treasury), deb);
    }
}
