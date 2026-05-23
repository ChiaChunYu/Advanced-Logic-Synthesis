#include <lorina/aiger.hpp>

#include <mockturtle/algorithms/aig_balancing.hpp>
#include <mockturtle/algorithms/aig_resub.hpp>
#include <mockturtle/algorithms/cleanup.hpp>
#include <mockturtle/algorithms/cut_rewriting.hpp>
#include <mockturtle/algorithms/functional_reduction.hpp>
#include <mockturtle/algorithms/mig_algebraic_rewriting.hpp>
#include <mockturtle/algorithms/mig_resub.hpp>
#include <mockturtle/algorithms/node_resynthesis/sop_factoring.hpp>
#include <mockturtle/algorithms/node_resynthesis/xag_npn.hpp>
#include <mockturtle/algorithms/refactoring.hpp>
#include <mockturtle/algorithms/xag_algebraic_rewriting.hpp>
#include <mockturtle/algorithms/xag_balancing.hpp>
#include <mockturtle/algorithms/xag_optimization.hpp>
#include <mockturtle/algorithms/xag_resub.hpp>
#include <mockturtle/algorithms/xmg_algebraic_rewriting.hpp>
#include <mockturtle/algorithms/xmg_optimization.hpp>
#include <mockturtle/io/aiger_reader.hpp>
#include <mockturtle/io/write_aiger.hpp>
#include <mockturtle/networks/aig.hpp>
#include <mockturtle/networks/mig.hpp>
#include <mockturtle/networks/xag.hpp>
#include <mockturtle/networks/xmg.hpp>
#include <mockturtle/views/depth_view.hpp>
#include <mockturtle/views/fanout_view.hpp>

#include <exception>
#include <iostream>
#include <string>

namespace
{
struct Args
{
  std::string input_truth;
  std::string input_aig;
  std::string output_aig;
  std::string mode;
};

void usage( char const* argv0 )
{
  std::cerr << "usage: " << argv0
            << " --input-truth file.truth --input-aig input.aig --output-aig output.aig --mode mode\n";
}

bool parse_args( int argc, char** argv, Args& args )
{
  for ( int i = 1; i < argc; ++i )
  {
    std::string key = argv[i];
    if ( key == "--help" || key == "-h" )
    {
      usage( argv[0] );
      return false;
    }
    if ( i + 1 >= argc )
    {
      std::cerr << "missing value for " << key << "\n";
      return false;
    }
    std::string value = argv[++i];
    if ( key == "--input-truth" )
      args.input_truth = value;
    else if ( key == "--input-aig" )
      args.input_aig = value;
    else if ( key == "--output-aig" )
      args.output_aig = value;
    else if ( key == "--mode" )
      args.mode = value;
    else
    {
      std::cerr << "unknown argument: " << key << "\n";
      return false;
    }
  }
  if ( args.input_aig.empty() || args.output_aig.empty() || args.mode.empty() )
  {
    usage( argv[0] );
    return false;
  }
  return true;
}

template<typename Ntk>
Ntk read_aiger_network( std::string const& path )
{
  Ntk ntk;
  if ( lorina::read_aiger( path, mockturtle::aiger_reader( ntk ) ) != lorina::return_code::success )
  {
    throw std::runtime_error( "failed to read AIGER: " + path );
  }
  return ntk;
}

template<typename Ntk>
void write_as_aiger( Ntk const& ntk, std::string const& path )
{
  auto aig = mockturtle::cleanup_dangling<Ntk, mockturtle::aig_network>( ntk );
  aig = mockturtle::cleanup_dangling( aig );
  mockturtle::write_aiger( aig, path );
}

void run_aig_resub( std::string const& input, std::string const& output )
{
  auto aig = read_aiger_network<mockturtle::aig_network>( input );

  mockturtle::aig_balancing_params bps;
  bps.fast_mode = true;
  mockturtle::aig_balance( aig, bps );

  mockturtle::xag_npn_resynthesis<mockturtle::aig_network> cut_resyn;
  mockturtle::cut_rewriting_params cps;
  cps.cut_enumeration_ps.cut_size = 4u;
  aig = mockturtle::cut_rewriting( aig, cut_resyn, cps );
  aig = mockturtle::cleanup_dangling( aig );

  mockturtle::sop_factoring<mockturtle::aig_network> sop_resyn;
  mockturtle::refactoring_params fps;
  mockturtle::refactoring( aig, sop_resyn, fps );
  aig = mockturtle::cleanup_dangling( aig );

  mockturtle::resubstitution_params rps;
  rps.max_pis = 8u;
  rps.max_inserts = 2u;
  rps.progress = false;
  mockturtle::depth_view depth_aig{ aig };
  mockturtle::fanout_view fanout_aig{ depth_aig };
  mockturtle::aig_resubstitution2( fanout_aig, rps );
  aig = mockturtle::cleanup_dangling( aig );

  mockturtle::aig_balance( aig, bps );
  write_as_aiger( aig, output );
}

void run_functional_reduction( std::string const& input, std::string const& output )
{
  auto aig = read_aiger_network<mockturtle::aig_network>( input );
  mockturtle::functional_reduction_params ps;
  mockturtle::functional_reduction( aig, ps );
  aig = mockturtle::cleanup_dangling( aig );
  write_as_aiger( aig, output );
}

void run_xag( std::string const& input, std::string const& output, bool heavy )
{
  auto xag = read_aiger_network<mockturtle::xag_network>( input );
  mockturtle::xag_balancing_params bps;
  bps.fast_mode = true;
  mockturtle::xag_balance( xag, bps );
  {
    mockturtle::depth_view depth_xag{ xag };
    mockturtle::xag_algebraic_depth_rewriting( depth_xag );
  }
  xag = mockturtle::cleanup_dangling( xag );
  if ( heavy )
  {
    xag = mockturtle::xag_constant_fanin_optimization( xag );
    mockturtle::resubstitution_params rps;
    rps.max_pis = 8u;
    rps.max_inserts = 1u;
    rps.progress = false;
    mockturtle::depth_view depth_xag{ xag };
    mockturtle::fanout_view fanout_xag{ depth_xag };
    mockturtle::xag_resubstitution( fanout_xag, rps );
    xag = mockturtle::cleanup_dangling( xag );
  }
  mockturtle::xag_balance( xag, bps );
  write_as_aiger( xag, output );
}

void run_mig( std::string const& input, std::string const& output, bool heavy )
{
  auto mig = read_aiger_network<mockturtle::mig_network>( input );
  {
    mockturtle::depth_view depth_mig{ mig };
    mockturtle::mig_algebraic_depth_rewriting( depth_mig );
  }
  mig = mockturtle::cleanup_dangling( mig );
  if ( heavy )
  {
    mockturtle::resubstitution_params rps;
    rps.max_pis = 8u;
    rps.max_inserts = 1u;
    rps.progress = false;
    mockturtle::depth_view depth_mig{ mig };
    mockturtle::fanout_view fanout_mig{ depth_mig };
    mockturtle::mig_resubstitution( fanout_mig, rps );
    mig = mockturtle::cleanup_dangling( mig );
  }
  write_as_aiger( mig, output );
}

void run_xmg( std::string const& input, std::string const& output, bool heavy )
{
  auto xmg = read_aiger_network<mockturtle::xmg_network>( input );
  {
    mockturtle::depth_view depth_xmg{ xmg };
    mockturtle::xmg_algebraic_depth_rewriting( depth_xmg );
  }
  xmg = mockturtle::cleanup_dangling( xmg );
  if ( heavy )
  {
    xmg = mockturtle::xmg_dont_cares_optimization( xmg );
    xmg = mockturtle::cleanup_dangling( xmg );
  }
  write_as_aiger( xmg, output );
}
} // namespace

int main( int argc, char** argv )
{
  Args args;
  if ( !parse_args( argc, argv, args ) )
    return 2;

  try
  {
    if ( args.mode == "aig_resub" )
      run_aig_resub( args.input_aig, args.output_aig );
    else if ( args.mode == "functional_reduction" )
      run_functional_reduction( args.input_aig, args.output_aig );
    else if ( args.mode == "xag_xor_heavy" )
      run_xag( args.input_aig, args.output_aig, true );
    else if ( args.mode == "roundtrip_xag" )
      run_xag( args.input_aig, args.output_aig, false );
    else if ( args.mode == "mig_majority" )
      run_mig( args.input_aig, args.output_aig, true );
    else if ( args.mode == "roundtrip_mig" )
      run_mig( args.input_aig, args.output_aig, false );
    else if ( args.mode == "xmg_arithmetic" )
      run_xmg( args.input_aig, args.output_aig, true );
    else if ( args.mode == "roundtrip_xmg" )
      run_xmg( args.input_aig, args.output_aig, false );
    else
    {
      std::cerr << "unsupported mode: " << args.mode << "\n";
      return 3;
    }
  }
  catch ( std::exception const& e )
  {
    std::cerr << "mockturtle_opt failed in mode " << args.mode << ": " << e.what() << "\n";
    return 1;
  }

  return 0;
}
