// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

interface IReentrancyHook {
    function hook() external;
}

/// @dev A malicious ERC20: when armed, it calls a hook on the recipient during transfer — the
///      realistic reentrancy vector into a token-moving escrow. USDC never does this; this
///      proves the guard holds even if the token is hostile.
contract ReentrantToken is ERC20 {
    address public hookTarget;
    bool public armed;

    constructor() ERC20("Reentrant", "RE") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function arm(address target) external {
        hookTarget = target;
        armed = true;
    }

    function transfer(address to, uint256 value) public override returns (bool) {
        if (armed && to == hookTarget) {
            armed = false; // one-shot, avoid infinite recursion
            IReentrancyHook(to).hook();
        }
        return super.transfer(to, value);
    }
}
