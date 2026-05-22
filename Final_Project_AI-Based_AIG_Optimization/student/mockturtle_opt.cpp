// Optional mockturtle-based AIG optimizer for flow_optimizer.py.
//
// Build with:
//   bash student/build_mockturtle_opt.sh
//
// Usage:
//   student/mockturtle input.aig output.aig [mode]
//
// The Python optimizer still performs ABC equivalence checking and ADP
// measurement before any generated output can be selected.

#include <lorina/aiger.hpp>

#include <mockturtle/algorithms/aig_balancing.hpp>
#include <mockturtle/algorithms/cleanup.hpp>
#include <mockturtle/algorithms/node_resynthesis/sop_factoring.hpp>
#include <mockturtle/algorithms/refactoring.hpp>
#include <mockturtle/io/aiger_reader.hpp>
#include <mockturtle/io/write_aiger.hpp>
#include <mockturtle/networks/aig.hpp>

#include <exception>
#include <iostream>
#include <string>

namespace
{
void run_balance( mockturtle::aig_network& aig )
{
  mockturtle::aig_balancing_params ps;
  ps.fast_mode = true;
  mockturtle::aig_balance( aig, ps );
}

void run_refactor( mockturtle::aig_network& aig )
{
  mockturtle::sop_factoring<mockturtle::aig_network> resyn;
  mockturtle::refactoring_params ps;
  mockturtle::refactoring( aig, resyn, ps );
  aig = mockturtle::cleanup_dangling( aig );
}

} // namespace

int main( int argc, char** argv )
{
  if ( argc < 3 || argc > 4 )
  {
    std::cerr << "usage: " << argv[0] << " input.aig output.aig [mode]\n";
    return 2;
  }

  std::string const input = argv[1];
  std::string const output = argv[2];
  std::string const mode = argc == 4 ? argv[3] : "compress2rs";

  try
  {
    mockturtle::aig_network aig;
    if ( lorina::read_aiger( input, mockturtle::aiger_reader( aig ) ) != lorina::return_code::success )
    {
      std::cerr << "failed to read input AIG: " << input << "\n";
      return 1;
    }

    if ( mode == "balance" )
    {
      run_balance( aig );
    }
    else if ( mode == "refactor" )
    {
      run_refactor( aig );
    }
    else if ( mode == "light" )
    {
      run_balance( aig );
      run_refactor( aig );
      run_balance( aig );
    }
    else
    {
      std::cerr << "unknown mode: " << mode << "\n";
      return 2;
    }

    mockturtle::write_aiger( aig, output );
  }
  catch ( std::exception const& e )
  {
    std::cerr << "mockturtle_opt error: " << e.what() << "\n";
    return 1;
  }

  return 0;
}
